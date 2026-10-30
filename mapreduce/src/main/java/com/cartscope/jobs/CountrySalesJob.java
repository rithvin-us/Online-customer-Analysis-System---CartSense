package com.cartscope.jobs;

import java.io.IOException;
import java.util.List;

import com.cartscope.io.Aggregate;
import com.cartscope.io.AggregateSumReducer;
import com.cartscope.jobs.support.KeyedAggregateMapper;
import com.cartscope.jobs.support.RankStage;
import com.cartscope.jobs.support.ValidatedRecord;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;

/**
 * Analysis D: geographical distribution of sales, keyed by {@code Country}.
 *
 * <h2>Three chained MapReduce jobs</h2>
 * <ol>
 *   <li><b>distinct-rollup</b> — the same two-key technique used by the
 *       monthly analysis: {@code country \t I \t invoice} groups the money,
 *       {@code country \t C \t customer} produces the distinct customer
 *       count.</li>
 *   <li><b>country-rollup</b> — one row per country.</li>
 *   <li><b>rank</b> — countries ordered by net revenue, descending.</li>
 * </ol>
 *
 * <p>Unlike the customer analyses, this one deliberately keeps records with no
 * {@code CustomerID}: the country of a sale is known even when the buyer is
 * not, so excluding them would understate every country's revenue. Only the
 * distinct customer count ignores them, and it is labelled "identifiable
 * customers" to say so.
 */
public class CountrySalesJob extends AbstractAnalysis {

    private static final String TYPE_INVOICE = "I";
    private static final String TYPE_CUSTOMER = "C";

    private static final int L_GROSS = 0;
    private static final int L_RETURNS = 1;
    private static final int L_QTY_SOLD = 2;
    private static final int L_QTY_RETURNED = 3;
    private static final int L_RECORDS = 4;
    private static final int L_WIDTH = 5;

    private static final int C_INVOICES = 5;
    private static final int C_COMPLETED_INVOICES = 6;
    private static final int C_CUSTOMERS = 7;
    private static final int C_WIDTH = 8;

    // Final row: country(0) gross(1) returns(2) net(3) distinct_invoices(4)
    //            completed_invoices(5) identifiable_customers(6)
    //            quantity_sold(7) quantity_returned(8) transaction_records(9)
    private static final int FINAL_NET_REVENUE_COLUMN = 3;

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        LINES_WITHOUT_CUSTOMER_ID,
        DISTINCT_INVOICES,
        DISTINCT_COUNTRY_CUSTOMERS,
        COUNTRIES_REPORTED
    }

    @Override
    protected String analysisName() {
        return "country_analysis";
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());

        Path distinctRollup = stagePath("distinct-rollup");
        Job stage1 = newJob("distinct-rollup");
        stage1.setMapperClass(CountryLineMapper.class);
        stage1.setCombinerClass(AggregateSumReducer.class);
        stage1.setReducerClass(CountryDistinctReducer.class);
        stage1.setNumReduceTasks(reducersFor("distinct-rollup", defaultReducers()));
        stage1.setMapOutputKeyClass(Text.class);
        stage1.setMapOutputValueClass(Aggregate.class);
        stage1.setOutputKeyClass(Text.class);
        stage1.setOutputValueClass(Aggregate.class);
        addInputs(stage1, inputPaths);
        setOutput(stage1, distinctRollup);
        if (!runStage("distinct-rollup", stage1, inputPaths, distinctRollup)) {
            return false;
        }

        Path byCountry = new Path(resultDir, "by_country");
        Job stage2 = newJob("country-rollup");
        KeyedAggregateMapper.configure(stage2, C_WIDTH, false);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(CountryRollupReducer.class);
        // Around forty countries: one reducer gives a single alphabetical file.
        stage2.setNumReduceTasks(reducersFor("country-rollup", 1));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, distinctRollup);
        setOutput(stage2, byCountry);
        if (!runStage("country-rollup", stage2, List.of(distinctRollup.toString()), byCountry)) {
            return false;
        }

        Path ranked = new Path(resultDir, "ranked_by_net_revenue");
        Job stage3 = newJob("rank");
        RankStage.configure(stage3, FINAL_NET_REVENUE_COLUMN, true, 0);
        addInput(stage3, byCountry);
        setOutput(stage3, ranked);
        if (!runStage("rank", stage3, List.of(byCountry.toString()), ranked)) {
            return false;
        }

        reporter.addOutput("by_country", byCountry.toString());
        reporter.addOutput("ranked_by_net_revenue", ranked.toString());
        return true;
    }

    // =====================================================================

    public static class CountryLineMapper extends Mapper<Object, Text, Text, Aggregate> {

        private final ValidatedRecord record = new ValidatedRecord();
        private final Text invoiceKey = new Text();
        private final Text customerKey = new Text();
        private final Aggregate empty = Aggregate.zeros(L_WIDTH);

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            if (!record.parse(value.toString())) {
                context.getCounter(Stat.MALFORMED_VALIDATED_RECORDS).increment(1L);
                return;
            }
            String country = record.country();

            Aggregate metrics = Aggregate.zeros(L_WIDTH);
            metrics.set(L_RECORDS, 1.0d);
            if (record.isSale()) {
                metrics.set(L_GROSS, record.lineValue());
                metrics.set(L_QTY_SOLD, record.quantity());
            } else {
                metrics.set(L_RETURNS, record.absValue());
                metrics.set(L_QTY_RETURNED, Math.abs(record.quantity()));
            }

            invoiceKey.set(country + "\t" + TYPE_INVOICE + "\t" + record.invoiceNo());
            context.write(invoiceKey, metrics);

            if (record.hasCustomerId()) {
                customerKey.set(country + "\t" + TYPE_CUSTOMER + "\t" + record.customerId());
                context.write(customerKey, empty);
            } else {
                context.getCounter(Stat.LINES_WITHOUT_CUSTOMER_ID).increment(1L);
            }
        }
    }

    public static class CountryDistinctReducer
            extends Reducer<Text, Aggregate, Text, Aggregate> {

        private final Text countryKey = new Text();

        @Override
        protected void reduce(Text compositeKey, Iterable<Aggregate> values, Context context)
                throws IOException, InterruptedException {
            Aggregate group = Aggregate.zeros(L_WIDTH);
            for (Aggregate value : values) {
                group.merge(value);
            }

            String[] parts = compositeKey.toString().split("\t", 3);
            String country = parts[0];
            String type = parts.length > 1 ? parts[1] : TYPE_INVOICE;

            Aggregate out = Aggregate.zeros(C_WIDTH);
            if (TYPE_CUSTOMER.equals(type)) {
                out.set(C_CUSTOMERS, 1.0d);
                context.getCounter(Stat.DISTINCT_COUNTRY_CUSTOMERS).increment(1L);
            } else {
                double gross = group.get(L_GROSS);
                double returns = group.get(L_RETURNS);
                for (int i = 0; i < L_WIDTH; i++) {
                    out.set(i, group.get(i));
                }
                out.set(C_INVOICES, 1.0d);
                out.set(C_COMPLETED_INVOICES, gross - returns > 0.0d ? 1.0d : 0.0d);
                context.getCounter(Stat.DISTINCT_INVOICES).increment(1L);
            }

            countryKey.set(country);
            context.write(countryKey, out);
        }
    }

    /**
     * Produces the reported country row.
     *
     * <p>Output columns, tab separated:
     * {@code country, gross_revenue, returns, net_revenue, distinct_invoices,
     * completed_invoices, identifiable_customers, quantity_sold,
     * quantity_returned, transaction_records}.
     */
    public static class CountryRollupReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text country, Iterable<Aggregate> rows, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(C_WIDTH);
            for (Aggregate row : rows) {
                totals.merge(row);
            }

            double gross = CustomerSpendingJob.round2(totals.get(L_GROSS));
            double returns = CustomerSpendingJob.round2(totals.get(L_RETURNS));
            context.getCounter(Stat.COUNTRIES_REPORTED).increment(1L);

            out.set(gross
                    + "\t" + returns
                    + "\t" + CustomerSpendingJob.round2(gross - returns)
                    + "\t" + totals.getLong(C_INVOICES)
                    + "\t" + totals.getLong(C_COMPLETED_INVOICES)
                    + "\t" + totals.getLong(C_CUSTOMERS)
                    + "\t" + totals.getLong(L_QTY_SOLD)
                    + "\t" + totals.getLong(L_QTY_RETURNED)
                    + "\t" + totals.getLong(L_RECORDS));
            context.write(country, out);
        }
    }
}
