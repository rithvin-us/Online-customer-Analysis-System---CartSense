package com.cartscope.jobs;

import java.io.IOException;
import java.time.LocalDateTime;
import java.util.List;

import com.cartscope.io.Aggregate;
import com.cartscope.io.AggregateSumReducer;
import com.cartscope.util.CsvLineParser;
import com.cartscope.util.InvoiceDateParser;
import com.cartscope.util.RetailSchema;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.LongWritable;
import org.apache.hadoop.io.NullWritable;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;
import org.apache.hadoop.mapreduce.lib.output.LazyOutputFormat;
import org.apache.hadoop.mapreduce.lib.output.MultipleOutputs;
import org.apache.hadoop.mapreduce.lib.output.TextOutputFormat;

/**
 * Stage 0 of every CartScope pipeline: turn a raw retail CSV in HDFS into a
 * canonical, de-duplicated, classified dataset, and a companion file of
 * rejected records with the reason for each rejection.
 *
 * <h2>Why this is a MapReduce job and not Python</h2>
 * The cleaning rules are applied to every record of the dataset, so they are
 * applied by the mappers, in parallel, on the worker containers. Duplicate
 * detection needs a global view of the data, which is exactly what a shuffle
 * gives: identical records hash to the same reducer and collapse there.
 *
 * <h2>Business rules</h2>
 * <ul>
 *   <li>A record is <b>rejected</b> when the schema does not match, a numeric
 *       field cannot be parsed, the quantity is zero, the unit price is not
 *       strictly positive, or the invoice date cannot be parsed under any
 *       supported pattern. Rejected records are written out with their reason;
 *       they are never silently dropped and never repaired by guesswork.</li>
 *   <li>A record is classified <b>RETURN</b> when its invoice number starts
 *       with {@code C} (a cancellation) <em>or</em> its quantity is negative.
 *       The classification is a single exclusive label, which is what stops a
 *       cancelled negative-quantity line from being counted twice: it
 *       contributes to returns exactly once.</li>
 *   <li>Every other surviving record is classified <b>SALE</b>.</li>
 *   <li>A missing {@code CustomerID} is preserved as an empty field rather
 *       than rejected, because such records are still valid sales for the
 *       country and monthly analyses. The customer-level analyses filter them
 *       out themselves.</li>
 *   <li>The raw upload under {@code .../raw} is never modified. The canonical
 *       form is a new, additional representation.</li>
 * </ul>
 *
 * <h2>Output layout</h2>
 * The MapReduce job writes into the run's work directory and, on success, the
 * {@code validated} and {@code rejected} subtrees are moved into the dataset
 * version directory, giving the documented layout:
 * <pre>
 *   /cartscope/datasets/&lt;dataset&gt;/versions/&lt;version&gt;/raw
 *                                                        /validated
 *                                                        /rejected
 * </pre>
 */
public class ValidationJob extends AbstractAnalysis {

    public static final String OUT_VALIDATED = "validated";
    public static final String OUT_REJECTED = "rejected";

    /** Rejection reasons and classification tallies, reported as real counters. */
    public enum Stat {
        HEADER_RECORDS,
        BLANK_LINES,
        MALFORMED_QUOTING,
        WRONG_FIELD_COUNT,
        MISSING_INVOICE_NO,
        MISSING_STOCK_CODE,
        UNPARSEABLE_QUANTITY,
        ZERO_QUANTITY,
        UNPARSEABLE_UNIT_PRICE,
        NON_POSITIVE_UNIT_PRICE,
        UNPARSEABLE_INVOICE_DATE,
        DUPLICATE_RECORDS,
        ACCEPTED_RECORDS,
        FULFILLED_SALES,
        RETURNS_AND_CANCELLATIONS,
        CANCELLATION_INVOICES,
        NEGATIVE_QUANTITY_LINES,
        MISSING_CUSTOMER_ID,
        MISSING_COUNTRY
    }

    @Override
    protected String analysisName() {
        return "validation";
    }

    /**
     * The target is a dataset version directory that already contains the raw
     * upload, so only the canonical subtrees must be absent.
     */
    @Override
    protected void checkResultDir(FileSystem fs) throws IOException {
        for (String subtree : new String[] {OUT_VALIDATED, OUT_REJECTED}) {
            Path path = new Path(resultDir, subtree);
            if (fs.exists(path)) {
                throw new IOException("this dataset version has already been validated: " + path);
            }
        }
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());
        Path stageOut = stagePath("canonicalise");

        Job job = newJob("canonicalise");
        job.setMapperClass(CanonicaliseMapper.class);
        job.setCombinerClass(AggregateSumReducer.class);
        job.setReducerClass(DedupeReducer.class);
        job.setNumReduceTasks(reducersFor("canonicalise", defaultReducers()));

        job.setMapOutputKeyClass(Text.class);
        job.setMapOutputValueClass(Aggregate.class);
        job.setOutputKeyClass(Text.class);
        job.setOutputValueClass(NullWritable.class);

        addInputs(job, inputPaths);
        setOutput(job, stageOut);

        // Only the named outputs are used, so the default part-r-* files would
        // all be empty. LazyOutputFormat suppresses them.
        LazyOutputFormat.setOutputFormatClass(job, TextOutputFormat.class);
        // Both named outputs carry the whole record in the key with a null
        // value, so that TextOutputFormat writes the line verbatim with no
        // trailing separator.
        MultipleOutputs.addNamedOutput(job, OUT_VALIDATED, TextOutputFormat.class,
                Text.class, NullWritable.class);
        MultipleOutputs.addNamedOutput(job, OUT_REJECTED, TextOutputFormat.class,
                Text.class, NullWritable.class);
        // With counters enabled, Hadoop reports exactly how many records each
        // named output received. Those counters are what the product uses for
        // the validated and rejected record counts, rather than the backend
        // counting rows itself.
        MultipleOutputs.setCountersEnabled(job, true);

        reporter.addSetting("cartscope.invoice.date.dayfirst",
                getConf().get(InvoiceDateParser.CONF_DAY_FIRST, "false"));

        if (!runStage("canonicalise", job, inputPaths, stageOut)) {
            return false;
        }

        promoteOutputs(stageOut);
        reporter.addOutput(OUT_VALIDATED, new Path(resultDir, OUT_VALIDATED).toString());
        reporter.addOutput(OUT_REJECTED, new Path(resultDir, OUT_REJECTED).toString());
        return true;
    }

    /**
     * Moves the two named output subtrees from the run's work directory into
     * the dataset version directory. A rename on HDFS is a NameNode metadata
     * operation, so no data is copied.
     */
    private void promoteOutputs(Path stageOut) throws IOException {
        FileSystem fs = resultDir.getFileSystem(getConf());
        fs.mkdirs(resultDir);
        for (String subtree : new String[] {OUT_VALIDATED, OUT_REJECTED}) {
            Path source = new Path(stageOut, subtree);
            Path target = new Path(resultDir, subtree);
            if (fs.exists(source)) {
                if (!fs.rename(source, target)) {
                    throw new IOException("could not move " + source + " to " + target);
                }
            } else {
                // No record fell into this category. An empty directory keeps
                // the layout uniform for the backend and the UI.
                fs.mkdirs(target);
            }
        }
    }

    // =====================================================================
    // Mapper
    // =====================================================================

    /**
     * Parses one raw CSV line, applies the cleaning rules, and emits a tagged
     * key so that the shuffle can collapse duplicates.
     *
     * <p>Both accepted and rejected records travel through the shuffle, tagged
     * {@code V} or {@code R}. Writing the rejected records from the reducer
     * instead of straight from the map task costs a little extra shuffle, and
     * buys two things: all of this job's output is produced by one committer,
     * and identical rejected lines are counted rather than repeated.
     *
     * <p>The value is a count of one. The combiner sums those counts, so each
     * reducer learns how many copies of a record existed without the copies
     * themselves crossing the network.
     */
    public static class CanonicaliseMapper
            extends Mapper<LongWritable, Text, Text, Aggregate> {

        /** Tag for a record that passed validation. */
        static final char TAG_VALID = 'V';
        /** Tag for a record that was rejected, carrying its reason. */
        static final char TAG_REJECT = 'R';

        private final CsvLineParser csv = new CsvLineParser();
        private final Text outKey = new Text();
        private final Aggregate one = Aggregate.of(1.0d);
        private InvoiceDateParser dates;
        private StringBuilder builder;

        @Override
        protected void setup(Context context) {
            boolean dayFirst = context.getConfiguration()
                    .getBoolean(InvoiceDateParser.CONF_DAY_FIRST, false);
            dates = new InvoiceDateParser(dayFirst);
            builder = new StringBuilder(256);
        }

        private void reject(Context context, Stat stat, String rawLine)
                throws IOException, InterruptedException {
            context.getCounter(stat).increment(1L);
            outKey.set(TAG_REJECT + "\t" + stat.name() + "\t" + sanitise(rawLine));
            context.write(outKey, one);
        }

        @Override
        protected void map(LongWritable offset, Text value, Context context)
                throws IOException, InterruptedException {
            String line = value.toString();
            if (!line.isEmpty() && line.charAt(0) == '﻿') {
                line = line.substring(1);     // strip a UTF-8 BOM
            }
            if (line.isBlank()) {
                context.getCounter(Stat.BLANK_LINES).increment(1L);
                return;
            }
            // The header appears once per file, and with multiple input splits
            // only the split containing byte 0 can see it, so matching on
            // content rather than on offset is the reliable test.
            if (line.regionMatches(true, 0, RetailSchema.RAW_HEADERS[0], 0,
                    RetailSchema.RAW_HEADERS[0].length())) {
                context.getCounter(Stat.HEADER_RECORDS).increment(1L);
                return;
            }

            CsvLineParser.Result parsed = csv.parse(line);
            if (parsed.malformed()) {
                reject(context, Stat.MALFORMED_QUOTING, line);
                return;
            }
            if (parsed.size() != RetailSchema.RAW_FIELD_COUNT) {
                reject(context, Stat.WRONG_FIELD_COUNT, line);
                return;
            }

            String invoiceNo = parsed.get(RetailSchema.RAW_INVOICE_NO);
            if (invoiceNo.isEmpty()) {
                reject(context, Stat.MISSING_INVOICE_NO, line);
                return;
            }
            String stockCode = parsed.get(RetailSchema.RAW_STOCK_CODE);
            if (stockCode.isEmpty()) {
                reject(context, Stat.MISSING_STOCK_CODE, line);
                return;
            }

            long quantity;
            try {
                quantity = Long.parseLong(parsed.get(RetailSchema.RAW_QUANTITY));
            } catch (NumberFormatException notANumber) {
                reject(context, Stat.UNPARSEABLE_QUANTITY, line);
                return;
            }
            if (quantity == 0L) {
                reject(context, Stat.ZERO_QUANTITY, line);
                return;
            }

            double unitPrice;
            try {
                unitPrice = Double.parseDouble(parsed.get(RetailSchema.RAW_UNIT_PRICE));
            } catch (NumberFormatException notANumber) {
                reject(context, Stat.UNPARSEABLE_UNIT_PRICE, line);
                return;
            }
            if (!(unitPrice > 0.0d)) {
                // Catches zero, negative and NaN prices in one test.
                reject(context, Stat.NON_POSITIVE_UNIT_PRICE, line);
                return;
            }

            LocalDateTime timestamp = dates.parse(parsed.get(RetailSchema.RAW_INVOICE_DATE));
            if (timestamp == null) {
                reject(context, Stat.UNPARSEABLE_INVOICE_DATE, line);
                return;
            }

            String customerId = normaliseCustomerId(parsed.get(RetailSchema.RAW_CUSTOMER_ID));
            if (customerId.isEmpty()) {
                context.getCounter(Stat.MISSING_CUSTOMER_ID).increment(1L);
            }
            String country = parsed.get(RetailSchema.RAW_COUNTRY);
            if (country.isEmpty()) {
                country = "Unspecified";
                context.getCounter(Stat.MISSING_COUNTRY).increment(1L);
            }

            boolean cancellation = invoiceNo.charAt(0) == 'C' || invoiceNo.charAt(0) == 'c';
            boolean negativeQuantity = quantity < 0L;
            if (cancellation) {
                context.getCounter(Stat.CANCELLATION_INVOICES).increment(1L);
            }
            if (negativeQuantity) {
                context.getCounter(Stat.NEGATIVE_QUANTITY_LINES).increment(1L);
            }

            // One exclusive class per record: a cancelled line with a negative
            // quantity is a single reversal, not two.
            boolean isReturn = cancellation || negativeQuantity;
            if (isReturn) {
                context.getCounter(Stat.RETURNS_AND_CANCELLATIONS).increment(1L);
            } else {
                context.getCounter(Stat.FULFILLED_SALES).increment(1L);
            }
            context.getCounter(Stat.ACCEPTED_RECORDS).increment(1L);

            double lineValue = quantity * unitPrice;
            double absValue = Math.abs(quantity) * unitPrice;

            builder.setLength(0);
            builder.append(invoiceNo).append('\t')
                    .append(stockCode).append('\t')
                    .append(sanitise(parsed.get(RetailSchema.RAW_DESCRIPTION))).append('\t')
                    .append(quantity).append('\t')
                    .append(InvoiceDateParser.toEpochMillis(timestamp)).append('\t')
                    .append(timestamp.format(InvoiceDateParser.CANONICAL)).append('\t')
                    .append(timestamp.format(InvoiceDateParser.MONTH_BUCKET)).append('\t')
                    .append(round2(unitPrice)).append('\t')
                    .append(customerId).append('\t')
                    .append(sanitise(country)).append('\t')
                    .append(round2(lineValue)).append('\t')
                    .append(round2(absValue)).append('\t')
                    .append(isReturn ? RetailSchema.CLASS_RETURN : RetailSchema.CLASS_SALE);

            outKey.set(TAG_VALID + "\t" + builder);
            context.write(outKey, one);
        }

        /**
         * Spreadsheet exports of this dataset frequently render the numeric
         * CustomerID column as {@code 17850.0}. The trailing {@code .0} is a
         * formatting artefact, not part of the identifier, so it is removed;
         * otherwise the same customer would appear under two ids across
         * differently exported versions of the same data.
         */
        static String normaliseCustomerId(String raw) {
            String value = raw.trim();
            if (value.isEmpty() || value.equalsIgnoreCase("NA")
                    || value.equalsIgnoreCase("NaN") || value.equalsIgnoreCase("null")) {
                return "";
            }
            if (value.endsWith(".0")) {
                value = value.substring(0, value.length() - 2);
            }
            return value;
        }

        /** Removes the field and record separators of the canonical format. */
        static String sanitise(String text) {
            if (text.indexOf('\t') < 0 && text.indexOf('\n') < 0 && text.indexOf('\r') < 0) {
                return text;
            }
            return text.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
        }

        static String round2(double value) {
            return Double.toString(Math.round(value * 100.0d) / 100.0d);
        }
    }

    // =====================================================================
    // Reducer
    // =====================================================================

    /**
     * Collapses identical records and routes them to the right output.
     *
     * <p>Every copy of a record arrives at the same reducer because the tagged
     * record text is the shuffle key. An accepted record is written once to the
     * validated output and its surplus copies are reported as duplicates; a
     * rejected record is written once to the rejected output with the number of
     * copies that carried the same fault.
     */
    public static class DedupeReducer
            extends Reducer<Text, Aggregate, Text, NullWritable> {

        private MultipleOutputs<Text, NullWritable> outputs;
        private final Text payload = new Text();

        @Override
        protected void setup(Context context) {
            outputs = new MultipleOutputs<>(context);
        }

        @Override
        protected void cleanup(Context context) throws IOException, InterruptedException {
            outputs.close();
        }

        @Override
        protected void reduce(Text tagged, Iterable<Aggregate> counts, Context context)
                throws IOException, InterruptedException {
            long copies = 0L;
            for (Aggregate count : counts) {
                copies += count.getLong(0);
            }

            String key = tagged.toString();
            char tag = key.charAt(0);

            if (tag == CanonicaliseMapper.TAG_VALID) {
                String canonical = key.substring(2);
                payload.set(canonical);
                outputs.write(OUT_VALIDATED, payload, NullWritable.get(),
                        OUT_VALIDATED + "/part");
                if (copies > 1L) {
                    long removed = copies - 1L;
                    context.getCounter(Stat.DUPLICATE_RECORDS).increment(removed);
                    payload.set(Stat.DUPLICATE_RECORDS.name() + "\t" + removed + "\t" + canonical);
                    outputs.write(OUT_REJECTED, payload, NullWritable.get(),
                            OUT_REJECTED + "/part");
                }
                return;
            }

            // Rejected records arrive as "R \t REASON \t original line" and are
            // written as "REASON \t copies \t original line".
            int reasonEnd = key.indexOf('\t', 2);
            payload.set(key.substring(2, reasonEnd) + "\t" + copies + "\t"
                    + key.substring(reasonEnd + 1));
            outputs.write(OUT_REJECTED, payload, NullWritable.get(), OUT_REJECTED + "/part");
        }
    }
}
