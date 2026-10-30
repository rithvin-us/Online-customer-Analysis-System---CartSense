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
 * Analysis A: customer spending behaviour.
 *
 * <h2>Three chained MapReduce jobs</h2>
 * <ol>
 *   <li><b>invoice-rollup</b> — group by {@code (customer, invoice)}. This
 *       stage exists purely to make the invoice count correct. An invoice has
 *       many lines, so counting invoices by counting records would multiply
 *       every customer's order count by their basket size. Grouping on the
 *       pair first collapses each invoice to exactly one row, after which
 *       counting is trivial.</li>
 *   <li><b>customer-rollup</b> — group the invoice rows by customer and
 *       produce the reported figures.</li>
 *   <li><b>rank</b> — order customers by net spending, descending.</li>
 * </ol>
 *
 * <h2>Scope rule</h2>
 * Records with no {@code CustomerID} are excluded here, because a customer
 * level figure cannot be attributed to an unknown customer. They are counted
 * in the {@code SKIPPED_MISSING_CUSTOMER_ID} counter so the exclusion is
 * visible, and they remain part of the monthly and country analyses.
 *
 * <h2>Definitions</h2>
 * <ul>
 *   <li><b>total_orders</b> — distinct invoices whose net value is positive,
 *       that is, completed orders. A pure cancellation invoice is not an
 *       order.</li>
 *   <li><b>gross_spending</b> — sum of fulfilled sale line values.</li>
 *   <li><b>returns</b> — sum of the absolute value of reversal lines.</li>
 *   <li><b>net_spending</b> — gross_spending minus returns.</li>
 *   <li><b>average_order_value</b> — gross_spending divided by total_orders.
 *       Zero when the customer has no completed order.</li>
 * </ul>
 */
public class CustomerSpendingJob extends AbstractAnalysis {

    // Metric layout of the invoice-rollup stage output.
    private static final int INV_GROSS = 0;
    private static final int INV_RETURNS = 1;
    private static final int INV_SALE_LINES = 2;
    private static final int INV_RETURN_LINES = 3;
    private static final int INV_WIDTH = 4;

    // Metric layout of the customer-rollup stage input (per invoice row).
    private static final int CUS_GROSS = 0;
    private static final int CUS_RETURNS = 1;
    private static final int CUS_SALE_LINES = 2;
    private static final int CUS_RETURN_LINES = 3;
    private static final int CUS_COMPLETED_INVOICES = 4;
    private static final int CUS_INVOICES_TOUCHED = 5;
    private static final int CUS_WIDTH = 6;

    /** Column index of net_spending in the final row, used by the ranking stage. */
    private static final int FINAL_NET_SPENDING_COLUMN = 4;

    public enum Stat {
        SKIPPED_MISSING_CUSTOMER_ID,
        MALFORMED_VALIDATED_RECORDS,
        INVOICES_ROLLED_UP,
        CUSTOMERS_REPORTED,
        CUSTOMERS_WITH_NO_COMPLETED_ORDER
    }

    @Override
    protected String analysisName() {
        return "customer_analysis";
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());

        // ---- Stage 1: collapse each invoice to one row ---------------------
        Path invoiceRollup = stagePath("invoice-rollup");
        Job stage1 = newJob("invoice-rollup");
        stage1.setMapperClass(InvoiceLineMapper.class);
        stage1.setCombinerClass(AggregateSumReducer.class);
        stage1.setReducerClass(InvoiceRollupReducer.class);
        stage1.setNumReduceTasks(reducersFor("invoice-rollup", defaultReducers()));
        stage1.setMapOutputKeyClass(Text.class);
        stage1.setMapOutputValueClass(Aggregate.class);
        stage1.setOutputKeyClass(Text.class);
        stage1.setOutputValueClass(Aggregate.class);
        addInputs(stage1, inputPaths);
        setOutput(stage1, invoiceRollup);
        if (!runStage("invoice-rollup", stage1, inputPaths, invoiceRollup)) {
            return false;
        }

        // ---- Stage 2: one row per customer --------------------------------
        Path byCustomer = new Path(resultDir, "by_customer");
        Job stage2 = newJob("customer-rollup");
        KeyedAggregateMapper.configure(stage2, CUS_WIDTH, false);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(CustomerRollupReducer.class);
        stage2.setNumReduceTasks(reducersFor("customer-rollup", defaultReducers()));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, invoiceRollup);
        setOutput(stage2, byCustomer);
        if (!runStage("customer-rollup", stage2, List.of(invoiceRollup.toString()), byCustomer)) {
            return false;
        }

        // ---- Stage 3: rank by net spending -------------------------------
        Path ranked = new Path(resultDir, "ranked_by_net_spending");
        Job stage3 = newJob("rank");
        RankStage.configure(stage3, FINAL_NET_SPENDING_COLUMN, true,
                getConf().getInt("cartscope.rank.limit.customers", 0));
        addInput(stage3, byCustomer);
        setOutput(stage3, ranked);
        if (!runStage("rank", stage3, List.of(byCustomer.toString()), ranked)) {
            return false;
        }

        reporter.addOutput("by_customer", byCustomer.toString());
        reporter.addOutput("ranked_by_net_spending", ranked.toString());
        return true;
    }

    // =====================================================================

    /**
     * Emits one record per validated line, keyed by customer and invoice.
     *
     * <p>The key is {@code customerId \t invoiceNo}, so the shuffle groups all
     * of an invoice's lines together regardless of which input split they came
     * from.
     */
    public static class InvoiceLineMapper extends Mapper<Object, Text, Text, Aggregate> {

        private final ValidatedRecord record = new ValidatedRecord();
        private final Text outKey = new Text();

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            if (!record.parse(value.toString())) {
                context.getCounter(Stat.MALFORMED_VALIDATED_RECORDS).increment(1L);
                return;
            }
            if (!record.hasCustomerId()) {
                context.getCounter(Stat.SKIPPED_MISSING_CUSTOMER_ID).increment(1L);
                return;
            }

            Aggregate metrics = Aggregate.zeros(INV_WIDTH);
            if (record.isSale()) {
                metrics.set(INV_GROSS, record.lineValue());
                metrics.set(INV_SALE_LINES, 1.0d);
            } else {
                metrics.set(INV_RETURNS, record.absValue());
                metrics.set(INV_RETURN_LINES, 1.0d);
            }

            outKey.set(record.customerId() + "\t" + record.invoiceNo());
            context.write(outKey, metrics);
        }
    }

    /**
     * Collapses an invoice's lines into a single row and re-keys it by
     * customer, adding the two invoice-level flags that the next stage sums:
     * whether the invoice is a completed order, and that it is one invoice.
     */
    public static class InvoiceRollupReducer
            extends Reducer<Text, Aggregate, Text, Aggregate> {

        private final Text customerKey = new Text();

        @Override
        protected void reduce(Text customerAndInvoice, Iterable<Aggregate> lines, Context context)
                throws IOException, InterruptedException {
            Aggregate invoice = Aggregate.zeros(INV_WIDTH);
            for (Aggregate line : lines) {
                invoice.merge(line);
            }

            double gross = invoice.get(INV_GROSS);
            double returns = invoice.get(INV_RETURNS);

            Aggregate out = Aggregate.zeros(CUS_WIDTH);
            out.set(CUS_GROSS, gross);
            out.set(CUS_RETURNS, returns);
            out.set(CUS_SALE_LINES, invoice.get(INV_SALE_LINES));
            out.set(CUS_RETURN_LINES, invoice.get(INV_RETURN_LINES));
            // A completed order: the invoice carries net positive value.
            out.set(CUS_COMPLETED_INVOICES, gross - returns > 0.0d ? 1.0d : 0.0d);
            out.set(CUS_INVOICES_TOUCHED, 1.0d);

            String key = customerAndInvoice.toString();
            customerKey.set(key.substring(0, key.indexOf('\t')));
            context.getCounter(Stat.INVOICES_ROLLED_UP).increment(1L);
            context.write(customerKey, out);
        }
    }

    /**
     * Produces the reported customer row.
     *
     * <p>Output columns, tab separated:
     * {@code customer_id, total_orders, gross_spending, returns, net_spending,
     * average_order_value, returned_lines, invoices_touched}.
     */
    public static class CustomerRollupReducer
            extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text customerId, Iterable<Aggregate> invoices, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(CUS_WIDTH);
            for (Aggregate invoice : invoices) {
                totals.merge(invoice);
            }

            double gross = round2(totals.get(CUS_GROSS));
            double returns = round2(totals.get(CUS_RETURNS));
            double net = round2(gross - returns);
            long completedOrders = totals.getLong(CUS_COMPLETED_INVOICES);
            double averageOrderValue = completedOrders > 0L ? round2(gross / completedOrders) : 0.0d;

            if (completedOrders == 0L) {
                context.getCounter(Stat.CUSTOMERS_WITH_NO_COMPLETED_ORDER).increment(1L);
            }
            context.getCounter(Stat.CUSTOMERS_REPORTED).increment(1L);

            out.set(completedOrders
                    + "\t" + gross
                    + "\t" + returns
                    + "\t" + net
                    + "\t" + averageOrderValue
                    + "\t" + totals.getLong(CUS_RETURN_LINES)
                    + "\t" + totals.getLong(CUS_INVOICES_TOUCHED));
            context.write(customerId, out);
        }
    }

    static double round2(double value) {
        return Math.round(value * 100.0d) / 100.0d;
    }
}
