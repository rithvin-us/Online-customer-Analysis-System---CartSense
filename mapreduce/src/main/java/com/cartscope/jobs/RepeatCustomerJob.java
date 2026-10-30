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
 * Analysis E: customer loyalty and repeat purchasing.
 *
 * <h2>Why three MapReduce jobs</h2>
 * The definition of a repeat customer — "at least two distinct completed
 * invoices" — cannot be evaluated from a single pass over the transaction
 * lines, because a line does not know how many invoices its customer has, and
 * an invoice has many lines. The pipeline therefore narrows the data twice
 * before it draws a conclusion:
 *
 * <ol>
 *   <li><b>invoice-rollup</b> — group by {@code (customer, invoice)}: many
 *       lines become one invoice, and the invoice's net value decides whether
 *       it is a completed order.</li>
 *   <li><b>customer-rollup</b> — group by customer: many invoices become one
 *       customer with a completed invoice count and a net spend.</li>
 *   <li><b>cohort-summary</b> — a single group over all customers, producing
 *       the population level figures. The combiner does the per-split
 *       arithmetic, so the single reducer receives a handful of partial sums
 *       rather than one row per customer.</li>
 * </ol>
 *
 * <h2>Definitions</h2>
 * <ul>
 *   <li><b>Identified customer</b> — a customer id present in the validated
 *       data. Records with no {@code CustomerID} cannot be attributed and are
 *       excluded; the count of excluded lines is reported as a counter.</li>
 *   <li><b>Completed invoice</b> — a distinct invoice with net positive value.
 *       A cancellation-only invoice is not a purchase.</li>
 *   <li><b>Repeat customer</b> — two or more completed invoices.</li>
 *   <li><b>Average purchase frequency</b> — completed invoices divided by the
 *       number of customers with at least one completed invoice. Customers who
 *       only ever cancelled would otherwise drag the average down while having
 *       never purchased.</li>
 * </ul>
 */
public class RepeatCustomerJob extends AbstractAnalysis {

    private static final int INV_GROSS = 0;
    private static final int INV_RETURNS = 1;
    private static final int INV_WIDTH = 2;

    // Per-customer row exchanged between stage 1 and stage 2.
    private static final int CUS_COMPLETED_INVOICES = 0;
    private static final int CUS_NET_SPEND = 1;
    private static final int CUS_INVOICES_TOUCHED = 2;
    private static final int CUS_WIDTH = 3;

    // Cohort accumulator of stage 3.
    private static final int COH_CUSTOMERS = 0;
    private static final int COH_SINGLE = 1;
    private static final int COH_REPEAT = 2;
    private static final int COH_NO_PURCHASE = 3;
    private static final int COH_COMPLETED_INVOICES = 4;
    private static final int COH_NET_ALL = 5;
    private static final int COH_NET_REPEAT = 6;
    private static final int COH_NET_SINGLE = 7;
    private static final int COH_WIDTH = 8;

    private static final String COHORT_KEY = "ALL";

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        SKIPPED_MISSING_CUSTOMER_ID,
        INVOICES_ROLLED_UP,
        CUSTOMERS_ROLLED_UP,
        REPEAT_CUSTOMERS,
        SINGLE_INVOICE_CUSTOMERS,
        CUSTOMERS_WITHOUT_COMPLETED_INVOICE
    }

    @Override
    protected String analysisName() {
        return "repeat_customers";
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());

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

        Path byCustomer = new Path(resultDir, "by_customer");
        Job stage2 = newJob("customer-rollup");
        KeyedAggregateMapper.configure(stage2, CUS_WIDTH, false);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(CustomerLoyaltyReducer.class);
        stage2.setNumReduceTasks(reducersFor("customer-rollup", defaultReducers()));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, invoiceRollup);
        setOutput(stage2, byCustomer);
        if (!runStage("customer-rollup", stage2, List.of(invoiceRollup.toString()), byCustomer)) {
            return false;
        }

        Path summary = new Path(resultDir, "summary");
        Job stage3 = newJob("cohort-summary");
        stage3.setMapperClass(CohortMapper.class);
        stage3.setCombinerClass(AggregateSumReducer.class);
        stage3.setReducerClass(CohortSummaryReducer.class);
        // A population summary is one group, so one reducer.
        stage3.setNumReduceTasks(1);
        stage3.setMapOutputKeyClass(Text.class);
        stage3.setMapOutputValueClass(Aggregate.class);
        stage3.setOutputKeyClass(Text.class);
        stage3.setOutputValueClass(Text.class);
        addInput(stage3, byCustomer);
        setOutput(stage3, summary);
        if (!runStage("cohort-summary", stage3, List.of(byCustomer.toString()), summary)) {
            return false;
        }

        reporter.addOutput("by_customer", byCustomer.toString());
        reporter.addOutput("summary", summary.toString());
        return true;
    }

    // =====================================================================

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
            } else {
                metrics.set(INV_RETURNS, record.absValue());
            }
            outKey.set(record.customerId() + "\t" + record.invoiceNo());
            context.write(outKey, metrics);
        }
    }

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
            double net = invoice.get(INV_GROSS) - invoice.get(INV_RETURNS);

            Aggregate out = Aggregate.zeros(CUS_WIDTH);
            out.set(CUS_COMPLETED_INVOICES, net > 0.0d ? 1.0d : 0.0d);
            out.set(CUS_NET_SPEND, net);
            out.set(CUS_INVOICES_TOUCHED, 1.0d);

            String key = customerAndInvoice.toString();
            customerKey.set(key.substring(0, key.indexOf('\t')));
            context.getCounter(Stat.INVOICES_ROLLED_UP).increment(1L);
            context.write(customerKey, out);
        }
    }

    /**
     * One row per customer.
     *
     * <p>Output columns, tab separated:
     * {@code customer_id, completed_invoices, net_spend, invoices_touched,
     * is_repeat_customer}.
     */
    public static class CustomerLoyaltyReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text customerId, Iterable<Aggregate> invoices, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(CUS_WIDTH);
            for (Aggregate invoice : invoices) {
                totals.merge(invoice);
            }

            long completed = totals.getLong(CUS_COMPLETED_INVOICES);
            boolean repeat = completed >= 2L;
            if (repeat) {
                context.getCounter(Stat.REPEAT_CUSTOMERS).increment(1L);
            } else if (completed == 1L) {
                context.getCounter(Stat.SINGLE_INVOICE_CUSTOMERS).increment(1L);
            } else {
                context.getCounter(Stat.CUSTOMERS_WITHOUT_COMPLETED_INVOICE).increment(1L);
            }
            context.getCounter(Stat.CUSTOMERS_ROLLED_UP).increment(1L);

            out.set(completed
                    + "\t" + CustomerSpendingJob.round2(totals.get(CUS_NET_SPEND))
                    + "\t" + totals.getLong(CUS_INVOICES_TOUCHED)
                    + "\t" + (repeat ? 1 : 0));
            context.write(customerId, out);
        }
    }

    /** Folds every customer row into a single cohort group. */
    public static class CohortMapper extends Mapper<Object, Text, Text, Aggregate> {

        private final Text cohort = new Text(COHORT_KEY);

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            String[] fields = value.toString().split("\t", -1);
            if (fields.length < 4) {
                return;
            }
            long completed;
            double netSpend;
            try {
                completed = Long.parseLong(fields[1]);
                netSpend = Double.parseDouble(fields[2]);
            } catch (NumberFormatException notANumber) {
                return;
            }

            Aggregate metrics = Aggregate.zeros(COH_WIDTH);
            metrics.set(COH_CUSTOMERS, 1.0d);
            metrics.set(COH_COMPLETED_INVOICES, completed);
            metrics.set(COH_NET_ALL, netSpend);
            if (completed >= 2L) {
                metrics.set(COH_REPEAT, 1.0d);
                metrics.set(COH_NET_REPEAT, netSpend);
            } else if (completed == 1L) {
                metrics.set(COH_SINGLE, 1.0d);
                metrics.set(COH_NET_SINGLE, netSpend);
            } else {
                metrics.set(COH_NO_PURCHASE, 1.0d);
            }
            context.write(cohort, metrics);
        }
    }

    /**
     * Emits the population figures as {@code metric \t value} rows, which keeps
     * the file self describing and trivially parseable by the backend.
     */
    public static class CohortSummaryReducer extends Reducer<Text, Aggregate, Text, Text> {

        @Override
        protected void reduce(Text cohort, Iterable<Aggregate> partials, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(COH_WIDTH);
            for (Aggregate partial : partials) {
                totals.merge(partial);
            }

            long customers = totals.getLong(COH_CUSTOMERS);
            long single = totals.getLong(COH_SINGLE);
            long repeat = totals.getLong(COH_REPEAT);
            long noPurchase = totals.getLong(COH_NO_PURCHASE);
            long completedInvoices = totals.getLong(COH_COMPLETED_INVOICES);
            long purchasers = single + repeat;

            emit(context, "identified_customers", customers);
            emit(context, "customers_with_single_completed_invoice", single);
            emit(context, "repeat_customers", repeat);
            emit(context, "customers_without_completed_invoice", noPurchase);
            emit(context, "total_completed_invoices", completedInvoices);
            emit(context, "purchasing_customers", purchasers);
            emit(context, "average_purchase_frequency",
                    purchasers > 0L ? round4((double) completedInvoices / purchasers) : 0.0d);
            emit(context, "repeat_customer_percentage",
                    purchasers > 0L ? round4(100.0d * repeat / purchasers) : 0.0d);
            emit(context, "repeat_customer_percentage_of_identified",
                    customers > 0L ? round4(100.0d * repeat / customers) : 0.0d);
            emit(context, "net_spend_all_customers",
                    CustomerSpendingJob.round2(totals.get(COH_NET_ALL)));
            emit(context, "average_net_spend_repeat_customers",
                    repeat > 0L ? CustomerSpendingJob.round2(totals.get(COH_NET_REPEAT) / repeat) : 0.0d);
            emit(context, "average_net_spend_single_invoice_customers",
                    single > 0L ? CustomerSpendingJob.round2(totals.get(COH_NET_SINGLE) / single) : 0.0d);
        }

        private void emit(Context context, String metric, double value)
                throws IOException, InterruptedException {
            context.write(new Text(metric), new Text(Double.toString(value)));
        }

        private void emit(Context context, String metric, long value)
                throws IOException, InterruptedException {
            context.write(new Text(metric), new Text(Long.toString(value)));
        }

        private static double round4(double value) {
            return Math.round(value * 10000.0d) / 10000.0d;
        }
    }
}
