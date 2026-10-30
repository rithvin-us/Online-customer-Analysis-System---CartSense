package com.cartscope.jobs;

import java.io.IOException;
import java.util.List;

import com.cartscope.io.Aggregate;
import com.cartscope.io.AggregateSumReducer;
import com.cartscope.jobs.support.KeyedAggregateMapper;
import com.cartscope.jobs.support.ValidatedRecord;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;

/**
 * Analysis B: monthly sales and returns.
 *
 * <h2>Two chained MapReduce jobs, and why the first one exists</h2>
 * A month's figures include two <em>distinct</em> counts — how many invoices
 * and how many identifiable customers it contains — and a distinct count
 * cannot be produced by summing. It needs the duplicates removed first, which
 * means a shuffle.
 *
 * <p>Stage 1 therefore emits two kinds of key:
 * <pre>
 *   &lt;month&gt; \t I \t &lt;invoice_no&gt;    carrying the money and quantity metrics
 *   &lt;month&gt; \t C \t &lt;customer_id&gt;   carrying no metrics
 * </pre>
 * Hadoop groups each key, so one invoice produces exactly one group no matter
 * how many lines it had, and one customer produces exactly one group per month
 * no matter how often they bought. The stage 1 reducer turns each group into a
 * single row keyed by month with a 1 in the right counting slot, and stage 2
 * simply adds the rows up.
 *
 * <p>Records with no {@code CustomerID} are kept in the money figures — they
 * are real sales — and only skipped for the distinct customer count, which is
 * reported as "identifiable customers" for that reason.
 */
public class MonthlySalesJob extends AbstractAnalysis {

    private static final String TYPE_INVOICE = "I";
    private static final String TYPE_CUSTOMER = "C";

    // Metric layout emitted by the stage 1 mapper.
    private static final int L_GROSS = 0;
    private static final int L_RETURNS = 1;
    private static final int L_SALE_LINES = 2;
    private static final int L_RETURN_LINES = 3;
    private static final int L_QTY_SOLD = 4;
    private static final int L_QTY_RETURNED = 5;
    private static final int L_WIDTH = 6;

    // Metric layout exchanged between stage 1 and stage 2.
    private static final int M_GROSS = 0;
    private static final int M_RETURNS = 1;
    private static final int M_SALE_LINES = 2;
    private static final int M_RETURN_LINES = 3;
    private static final int M_QTY_SOLD = 4;
    private static final int M_QTY_RETURNED = 5;
    private static final int M_INVOICES = 6;
    private static final int M_COMPLETED_INVOICES = 7;
    private static final int M_CUSTOMERS = 8;
    private static final int M_WIDTH = 9;

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        MISSING_MONTH,
        LINES_WITHOUT_CUSTOMER_ID,
        DISTINCT_INVOICES,
        DISTINCT_CUSTOMER_MONTHS,
        MONTHS_REPORTED
    }

    @Override
    protected String analysisName() {
        return "monthly_sales";
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());

        Path distinctRollup = stagePath("distinct-rollup");
        Job stage1 = newJob("distinct-rollup");
        stage1.setMapperClass(MonthlyLineMapper.class);
        stage1.setCombinerClass(AggregateSumReducer.class);
        stage1.setReducerClass(DistinctRollupReducer.class);
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

        Path byMonth = new Path(resultDir, "by_month");
        Job stage2 = newJob("month-rollup");
        KeyedAggregateMapper.configure(stage2, M_WIDTH, false);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(MonthRollupReducer.class);
        // One reducer: a monthly series has a few dozen keys at most, and a
        // single reducer yields one chronologically ordered file, which is what
        // a time series chart needs.
        stage2.setNumReduceTasks(reducersFor("month-rollup", 1));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, distinctRollup);
        setOutput(stage2, byMonth);
        if (!runStage("month-rollup", stage2, List.of(distinctRollup.toString()), byMonth)) {
            return false;
        }

        reporter.addOutput("by_month", byMonth.toString());
        return true;
    }

    // =====================================================================

    public static class MonthlyLineMapper extends Mapper<Object, Text, Text, Aggregate> {

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
            String month = record.month();
            if (month.isEmpty()) {
                context.getCounter(Stat.MISSING_MONTH).increment(1L);
                return;
            }

            Aggregate metrics = Aggregate.zeros(L_WIDTH);
            if (record.isSale()) {
                metrics.set(L_GROSS, record.lineValue());
                metrics.set(L_SALE_LINES, 1.0d);
                metrics.set(L_QTY_SOLD, record.quantity());
            } else {
                metrics.set(L_RETURNS, record.absValue());
                metrics.set(L_RETURN_LINES, 1.0d);
                metrics.set(L_QTY_RETURNED, Math.abs(record.quantity()));
            }

            invoiceKey.set(month + "\t" + TYPE_INVOICE + "\t" + record.invoiceNo());
            context.write(invoiceKey, metrics);

            if (record.hasCustomerId()) {
                customerKey.set(month + "\t" + TYPE_CUSTOMER + "\t" + record.customerId());
                context.write(customerKey, empty);
            } else {
                context.getCounter(Stat.LINES_WITHOUT_CUSTOMER_ID).increment(1L);
            }
        }
    }

    /**
     * Turns each distinct invoice group and each distinct customer-month group
     * into one row keyed by month.
     */
    public static class DistinctRollupReducer
            extends Reducer<Text, Aggregate, Text, Aggregate> {

        private final Text monthKey = new Text();

        @Override
        protected void reduce(Text compositeKey, Iterable<Aggregate> values, Context context)
                throws IOException, InterruptedException {
            Aggregate group = Aggregate.zeros(L_WIDTH);
            for (Aggregate value : values) {
                group.merge(value);
            }

            String[] parts = compositeKey.toString().split("\t", 3);
            String month = parts[0];
            String type = parts.length > 1 ? parts[1] : TYPE_INVOICE;

            Aggregate out = Aggregate.zeros(M_WIDTH);
            if (TYPE_CUSTOMER.equals(type)) {
                out.set(M_CUSTOMERS, 1.0d);
                context.getCounter(Stat.DISTINCT_CUSTOMER_MONTHS).increment(1L);
            } else {
                double gross = group.get(L_GROSS);
                double returns = group.get(L_RETURNS);
                out.set(M_GROSS, gross);
                out.set(M_RETURNS, returns);
                out.set(M_SALE_LINES, group.get(L_SALE_LINES));
                out.set(M_RETURN_LINES, group.get(L_RETURN_LINES));
                out.set(M_QTY_SOLD, group.get(L_QTY_SOLD));
                out.set(M_QTY_RETURNED, group.get(L_QTY_RETURNED));
                out.set(M_INVOICES, 1.0d);
                out.set(M_COMPLETED_INVOICES, gross - returns > 0.0d ? 1.0d : 0.0d);
                context.getCounter(Stat.DISTINCT_INVOICES).increment(1L);
            }

            monthKey.set(month);
            context.write(monthKey, out);
        }
    }

    /**
     * Produces the reported monthly row.
     *
     * <p>Output columns, tab separated:
     * {@code month, gross_revenue, returns, net_revenue, distinct_invoices,
     * completed_invoices, identifiable_customers, quantity_sold,
     * quantity_returned, sale_lines, return_lines}.
     */
    public static class MonthRollupReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text month, Iterable<Aggregate> rows, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(M_WIDTH);
            for (Aggregate row : rows) {
                totals.merge(row);
            }

            double gross = CustomerSpendingJob.round2(totals.get(M_GROSS));
            double returns = CustomerSpendingJob.round2(totals.get(M_RETURNS));
            context.getCounter(Stat.MONTHS_REPORTED).increment(1L);

            out.set(gross
                    + "\t" + returns
                    + "\t" + CustomerSpendingJob.round2(gross - returns)
                    + "\t" + totals.getLong(M_INVOICES)
                    + "\t" + totals.getLong(M_COMPLETED_INVOICES)
                    + "\t" + totals.getLong(M_CUSTOMERS)
                    + "\t" + totals.getLong(M_QTY_SOLD)
                    + "\t" + totals.getLong(M_QTY_RETURNED)
                    + "\t" + totals.getLong(M_SALE_LINES)
                    + "\t" + totals.getLong(M_RETURN_LINES));
            context.write(month, out);
        }
    }
}
