package com.cartscope.jobs;

import java.io.IOException;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import com.cartscope.io.Aggregate;
import com.cartscope.io.AggregateSumReducer;
import com.cartscope.jobs.support.KeyedAggregateMapper;
import com.cartscope.jobs.support.ValidatedRecord;
import com.cartscope.util.InvoiceDateParser;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;

/**
 * Analysis F: RFM segmentation (recency, frequency, monetary value).
 *
 * <h2>Four chained MapReduce jobs</h2>
 * <ol>
 *   <li><b>invoice-rollup</b> — group by {@code (customer, invoice)}. Recency
 *       is the <em>latest</em> timestamp, which is carried in
 *       {@link Aggregate}'s maximum-merged vector rather than its additive
 *       one, so that no combiner can ever add two timestamps together.</li>
 *   <li><b>customer-rollup</b> — one row per customer with frequency (distinct
 *       completed invoices), monetary value (net spend) and the timestamp of
 *       the last completed purchase.</li>
 *   <li><b>score</b> — assign the three scores and the segment.</li>
 *   <li><b>segment-summary</b> — size and value of each segment.</li>
 * </ol>
 *
 * <h2>Scoring rules, stated plainly</h2>
 * Scores are population quintiles, not hand-picked thresholds, so they adapt
 * to whichever dataset is loaded:
 * <ul>
 *   <li><b>R</b> — recency in days from the reference date. The reference date
 *       is the latest completed purchase anywhere in the dataset, so the
 *       scoring does not depend on when the analysis happens to be run, which
 *       keeps a run reproducible. The 20% of customers who bought most
 *       recently score 5, the next 20% score 4, and so on.</li>
 *   <li><b>F</b> — distinct completed invoices. Most frequent 20% score 5.</li>
 *   <li><b>M</b> — net spend. Highest spending 20% score 5.</li>
 * </ul>
 *
 * <p>Segments are then assigned by these rules, in order, first match wins:
 * <pre>
 *   R&ge;4 and F&ge;4 and M&ge;4  High-value customers
 *   F&ge;4 and M&ge;3            Loyal customers
 *   R&ge;4 and F&le;2            New customers
 *   R&ge;3 and F&ge;3            Potential loyalists
 *   R&le;2 and (F&ge;3 or M&ge;3) At-risk customers
 *   otherwise                    Needs attention
 * </pre>
 *
 * <p>No model is trained and nothing is inferred. The segment of any customer
 * can be re-derived by hand from the three scores in the output row.
 *
 * <h2>The one stage that holds data in memory</h2>
 * Quintile boundaries are a property of the whole customer population, so the
 * scoring stage runs with a single reducer that buffers one short row per
 * customer. That is bounded by the number of customers, not by the number of
 * transactions: the UCI dataset has about 4,400 and a one million record
 * synthetic dataset has tens of thousands, which is a few megabytes. For a
 * customer population large enough to matter, the same result would be
 * obtained by computing approximate quantiles in a separate pass and
 * broadcasting the boundaries to many reducers.
 */
public class RfmAnalysisJob extends AbstractAnalysis {

    private static final int INV_GROSS = 0;
    private static final int INV_RETURNS = 1;
    private static final int INV_WIDTH = 2;
    private static final int INV_MAX_TS = 0;
    private static final int INV_MAX_WIDTH = 1;

    private static final int CUS_FREQUENCY = 0;
    private static final int CUS_MONETARY = 1;
    private static final int CUS_INVOICES_TOUCHED = 2;
    private static final int CUS_WIDTH = 3;

    private static final int SEG_CUSTOMERS = 0;
    private static final int SEG_MONETARY = 1;
    private static final int SEG_FREQUENCY = 2;
    private static final int SEG_RECENCY = 3;
    private static final int SEG_WIDTH = 4;

    private static final String ALL_KEY = "ALL";

    /** Published so the backend can label the segments without duplicating them. */
    public static final String SEGMENT_HIGH_VALUE = "High-value customers";
    public static final String SEGMENT_LOYAL = "Loyal customers";
    public static final String SEGMENT_NEW = "New customers";
    public static final String SEGMENT_POTENTIAL = "Potential loyalists";
    public static final String SEGMENT_AT_RISK = "At-risk customers";
    public static final String SEGMENT_ATTENTION = "Needs attention";

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        SKIPPED_MISSING_CUSTOMER_ID,
        INVOICES_ROLLED_UP,
        CUSTOMERS_SCORED,
        CUSTOMERS_WITHOUT_PURCHASE_EXCLUDED
    }

    @Override
    protected String analysisName() {
        return "rfm_analysis";
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

        Path customerRollup = stagePath("customer-rollup");
        Job stage2 = newJob("customer-rollup");
        KeyedAggregateMapper.configure(stage2, CUS_WIDTH, INV_MAX_WIDTH, false);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(CustomerRfmReducer.class);
        stage2.setNumReduceTasks(reducersFor("customer-rollup", defaultReducers()));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, invoiceRollup);
        setOutput(stage2, customerRollup);
        if (!runStage("customer-rollup", stage2, List.of(invoiceRollup.toString()), customerRollup)) {
            return false;
        }

        Path scored = new Path(resultDir, "by_customer");
        Job stage3 = newJob("score");
        stage3.setMapperClass(ScoreFoldMapper.class);
        // No combiner: quintile boundaries are a property of the whole
        // population, so a partial aggregation on the map side cannot help.
        stage3.setReducerClass(ScoringReducer.class);
        stage3.setNumReduceTasks(1);
        stage3.setMapOutputKeyClass(Text.class);
        stage3.setMapOutputValueClass(Text.class);
        stage3.setOutputKeyClass(Text.class);
        stage3.setOutputValueClass(Text.class);
        addInput(stage3, customerRollup);
        setOutput(stage3, scored);
        if (!runStage("score", stage3, List.of(customerRollup.toString()), scored)) {
            return false;
        }

        Path bySegment = new Path(resultDir, "by_segment");
        Job stage4 = newJob("segment-summary");
        stage4.setMapperClass(SegmentMapper.class);
        stage4.setCombinerClass(AggregateSumReducer.class);
        stage4.setReducerClass(SegmentSummaryReducer.class);
        stage4.setNumReduceTasks(1);
        stage4.setMapOutputKeyClass(Text.class);
        stage4.setMapOutputValueClass(Aggregate.class);
        stage4.setOutputKeyClass(Text.class);
        stage4.setOutputValueClass(Text.class);
        addInput(stage4, scored);
        setOutput(stage4, bySegment);
        if (!runStage("segment-summary", stage4, List.of(scored.toString()), bySegment)) {
            return false;
        }

        reporter.addOutput("by_customer", scored.toString());
        reporter.addOutput("by_segment", bySegment.toString());
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

            Aggregate metrics = Aggregate.zeros(INV_WIDTH, INV_MAX_WIDTH);
            if (record.isSale()) {
                metrics.set(INV_GROSS, record.lineValue());
            } else {
                metrics.set(INV_RETURNS, record.absValue());
            }
            metrics.setMax(INV_MAX_TS, record.invoiceTimestamp());
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
            Aggregate invoice = Aggregate.zeros(INV_WIDTH, INV_MAX_WIDTH);
            for (Aggregate line : lines) {
                invoice.merge(line);
            }
            double net = invoice.get(INV_GROSS) - invoice.get(INV_RETURNS);
            boolean completed = net > 0.0d;

            Aggregate out = Aggregate.zeros(CUS_WIDTH, INV_MAX_WIDTH);
            out.set(CUS_FREQUENCY, completed ? 1.0d : 0.0d);
            out.set(CUS_MONETARY, net);
            out.set(CUS_INVOICES_TOUCHED, 1.0d);
            // Recency counts the last completed purchase. A cancellation is
            // not a purchase, so it must not refresh the customer's recency.
            if (completed) {
                out.setMax(INV_MAX_TS, invoice.getMax(INV_MAX_TS));
            }

            String key = customerAndInvoice.toString();
            customerKey.set(key.substring(0, key.indexOf('\t')));
            context.getCounter(Stat.INVOICES_ROLLED_UP).increment(1L);
            context.write(customerKey, out);
        }
    }

    /**
     * One row per customer: {@code customer_id, frequency, monetary,
     * invoices_touched, last_purchase_ts}.
     */
    public static class CustomerRfmReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text customerId, Iterable<Aggregate> invoices, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(CUS_WIDTH, INV_MAX_WIDTH);
            for (Aggregate invoice : invoices) {
                totals.merge(invoice);
            }
            out.set(totals.getLong(CUS_FREQUENCY)
                    + "\t" + CustomerSpendingJob.round2(totals.get(CUS_MONETARY))
                    + "\t" + totals.getLong(CUS_INVOICES_TOUCHED)
                    + "\t" + totals.getMaxLong(INV_MAX_TS));
            context.write(customerId, out);
        }
    }

    /** Folds every customer into one group so the quintiles can be computed. */
    public static class ScoreFoldMapper extends Mapper<Object, Text, Text, Text> {

        private final Text all = new Text(ALL_KEY);

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            if (value.getLength() > 0) {
                context.write(all, value);
            }
        }
    }

    /**
     * Assigns quintile scores and segments.
     *
     * <p>Output columns, tab separated: {@code customer_id, recency_days,
     * frequency, monetary, r_score, f_score, m_score, rfm_score, segment,
     * last_purchase_date}.
     */
    public static class ScoringReducer extends Reducer<Text, Text, Text, Text> {

        private static final class Customer {
            String id;
            long frequency;
            double monetary;
            long lastPurchaseTs;
            long recencyDays;
            int r;
            int f;
            int m;
        }

        @Override
        protected void reduce(Text all, Iterable<Text> rows, Context context)
                throws IOException, InterruptedException {
            List<Customer> customers = new ArrayList<>();
            long latestTs = Long.MIN_VALUE;

            for (Text row : rows) {
                String[] fields = row.toString().split("\t", -1);
                if (fields.length < 5) {
                    continue;
                }
                Customer customer = new Customer();
                customer.id = fields[0];
                try {
                    customer.frequency = Long.parseLong(fields[1]);
                    customer.monetary = Double.parseDouble(fields[2]);
                    customer.lastPurchaseTs = Long.parseLong(fields[4]);
                } catch (NumberFormatException notANumber) {
                    continue;
                }
                if (customer.frequency == 0L || customer.lastPurchaseTs <= 0L) {
                    // Never completed a purchase: recency is undefined, so the
                    // customer is reported in the counter and left unscored
                    // rather than given a fabricated score.
                    context.getCounter(Stat.CUSTOMERS_WITHOUT_PURCHASE_EXCLUDED).increment(1L);
                    continue;
                }
                latestTs = Math.max(latestTs, customer.lastPurchaseTs);
                customers.add(customer);
            }

            if (customers.isEmpty()) {
                return;
            }

            // Reference date: the latest completed purchase in the dataset.
            // Using the dataset rather than "now" is what makes a repeated run
            // over the same data produce identical scores.
            final long referenceTs = latestTs;
            for (Customer customer : customers) {
                customer.recencyDays = Duration.ofMillis(referenceTs - customer.lastPurchaseTs).toDays();
            }

            double[] recencies = customers.stream().mapToDouble(c -> c.recencyDays).toArray();
            double[] frequencies = customers.stream().mapToDouble(c -> c.frequency).toArray();
            double[] monetaries = customers.stream().mapToDouble(c -> c.monetary).toArray();
            Arrays.sort(recencies);
            Arrays.sort(frequencies);
            Arrays.sort(monetaries);

            for (Customer customer : customers) {
                // Recency is inverted: fewer days since the last purchase is a
                // better score.
                customer.r = 6 - quintile(recencies, customer.recencyDays);
                customer.f = quintile(frequencies, customer.frequency);
                customer.m = quintile(monetaries, customer.monetary);
            }

            LocalDateTime reference = InvoiceDateParser.fromEpochMillis(referenceTs);
            context.getCounter(Stat.CUSTOMERS_SCORED).increment(customers.size());

            for (Customer customer : customers) {
                String segment = segmentOf(customer.r, customer.f, customer.m);
                LocalDateTime lastPurchase = InvoiceDateParser.fromEpochMillis(customer.lastPurchaseTs);
                context.write(new Text(customer.id), new Text(
                        customer.recencyDays
                                + "\t" + customer.frequency
                                + "\t" + CustomerSpendingJob.round2(customer.monetary)
                                + "\t" + customer.r
                                + "\t" + customer.f
                                + "\t" + customer.m
                                + "\t" + ("" + customer.r + customer.f + customer.m)
                                + "\t" + segment
                                + "\t" + lastPurchase.format(InvoiceDateParser.CANONICAL)
                                + "\t" + reference.format(InvoiceDateParser.CANONICAL)));
            }
        }

        /**
         * Quintile of {@code value} within the sorted population, 1 (lowest
         * fifth) to 5 (highest fifth).
         */
        static int quintile(double[] sorted, double value) {
            int position = Arrays.binarySearch(sorted, value);
            if (position < 0) {
                position = -position - 1;
            }
            int bucket = (int) ((long) position * 5L / sorted.length) + 1;
            return Math.min(5, Math.max(1, bucket));
        }

        /** First matching rule wins; see the class comment for the table. */
        static String segmentOf(int r, int f, int m) {
            if (r >= 4 && f >= 4 && m >= 4) {
                return SEGMENT_HIGH_VALUE;
            }
            if (f >= 4 && m >= 3) {
                return SEGMENT_LOYAL;
            }
            if (r >= 4 && f <= 2) {
                return SEGMENT_NEW;
            }
            if (r >= 3 && f >= 3) {
                return SEGMENT_POTENTIAL;
            }
            if (r <= 2 && (f >= 3 || m >= 3)) {
                return SEGMENT_AT_RISK;
            }
            return SEGMENT_ATTENTION;
        }
    }

    /** Keys the scored rows by segment. */
    public static class SegmentMapper extends Mapper<Object, Text, Text, Aggregate> {

        private static final int COL_RECENCY = 1;
        private static final int COL_FREQUENCY = 2;
        private static final int COL_MONETARY = 3;
        private static final int COL_SEGMENT = 8;

        private final Text segment = new Text();

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            String[] fields = value.toString().split("\t", -1);
            if (fields.length <= COL_SEGMENT) {
                return;
            }
            Aggregate metrics = Aggregate.zeros(SEG_WIDTH);
            try {
                metrics.set(SEG_CUSTOMERS, 1.0d);
                metrics.set(SEG_RECENCY, Double.parseDouble(fields[COL_RECENCY]));
                metrics.set(SEG_FREQUENCY, Double.parseDouble(fields[COL_FREQUENCY]));
                metrics.set(SEG_MONETARY, Double.parseDouble(fields[COL_MONETARY]));
            } catch (NumberFormatException notANumber) {
                return;
            }
            segment.set(fields[COL_SEGMENT]);
            context.write(segment, metrics);
        }
    }

    /**
     * One row per segment: {@code segment, customers, total_monetary,
     * average_monetary, average_frequency, average_recency_days}.
     */
    public static class SegmentSummaryReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text segment, Iterable<Aggregate> rows, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(SEG_WIDTH);
            for (Aggregate row : rows) {
                totals.merge(row);
            }
            long customers = totals.getLong(SEG_CUSTOMERS);
            double monetary = totals.get(SEG_MONETARY);
            out.set(customers
                    + "\t" + CustomerSpendingJob.round2(monetary)
                    + "\t" + (customers > 0L ? CustomerSpendingJob.round2(monetary / customers) : 0.0d)
                    + "\t" + (customers > 0L
                            ? CustomerSpendingJob.round2(totals.get(SEG_FREQUENCY) / customers) : 0.0d)
                    + "\t" + (customers > 0L
                            ? CustomerSpendingJob.round2(totals.get(SEG_RECENCY) / customers) : 0.0d));
            context.write(segment, out);
        }
    }
}
