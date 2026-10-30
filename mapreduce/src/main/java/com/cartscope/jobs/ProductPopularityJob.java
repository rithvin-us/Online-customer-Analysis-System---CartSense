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
 * Analysis C: product popularity, keyed by {@code StockCode}.
 *
 * <h2>Five chained MapReduce jobs</h2>
 * <ol>
 *   <li><b>invoice-rollup</b> — group by {@code (stock_code, invoice_no)} so
 *       that "number of distinct invoices this product appeared on" is a
 *       count of groups rather than a count of lines.</li>
 *   <li><b>product-rollup</b> — one row per product.</li>
 *   <li><b>rank-revenue</b>, <b>rank-quantity</b>, <b>rank-returns</b> — three
 *       orderings of the same rows. The top ten by revenue, the top ten by
 *       quantity and the products with the heaviest return activity are the
 *       first ten rows of these three files.</li>
 * </ol>
 *
 * <h2>Product descriptions</h2>
 * {@code StockCode} is the identifier; {@code Description} is a label, and in
 * the source data one stock code can carry several spellings of its
 * description. The label is therefore collapsed with a deterministic rule —
 * the lexicographically smallest non-empty description — implemented in
 * {@link Aggregate#merge}. Without a deterministic rule, the product name
 * shown in the UI could change between two runs over identical data.
 */
public class ProductPopularityJob extends AbstractAnalysis {

    private static final int L_GROSS = 0;
    private static final int L_RETURNS = 1;
    private static final int L_QTY_SOLD = 2;
    private static final int L_QTY_RETURNED = 3;
    private static final int L_SALE_LINES = 4;
    private static final int L_RETURN_LINES = 5;
    private static final int L_WIDTH = 6;

    private static final int P_INVOICES = 6;
    private static final int P_WIDTH = 7;

    // Final row: stock_code(0) gross(1) returns(2) net(3) qty_sold(4)
    //            qty_returned(5) distinct_invoices(6) sale_lines(7)
    //            return_lines(8) description(9)
    private static final int FINAL_NET_REVENUE_COLUMN = 3;
    private static final int FINAL_QTY_SOLD_COLUMN = 4;
    private static final int FINAL_QTY_RETURNED_COLUMN = 5;

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        PRODUCT_INVOICE_GROUPS,
        PRODUCTS_REPORTED,
        PRODUCTS_WITH_RETURNS
    }

    @Override
    protected String analysisName() {
        return "product_analysis";
    }

    @Override
    protected boolean execute() throws Exception {
        applySplitSizeHint(getConf());

        Path invoiceRollup = stagePath("invoice-rollup");
        Job stage1 = newJob("invoice-rollup");
        stage1.setMapperClass(ProductLineMapper.class);
        stage1.setCombinerClass(AggregateSumReducer.class);
        stage1.setReducerClass(ProductInvoiceReducer.class);
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

        Path byProduct = new Path(resultDir, "by_product");
        Job stage2 = newJob("product-rollup");
        KeyedAggregateMapper.configure(stage2, P_WIDTH, true);
        stage2.setCombinerClass(AggregateSumReducer.class);
        stage2.setReducerClass(ProductRollupReducer.class);
        stage2.setNumReduceTasks(reducersFor("product-rollup", defaultReducers()));
        stage2.setOutputKeyClass(Text.class);
        stage2.setOutputValueClass(Text.class);
        addInput(stage2, invoiceRollup);
        setOutput(stage2, byProduct);
        if (!runStage("product-rollup", stage2, List.of(invoiceRollup.toString()), byProduct)) {
            return false;
        }

        reporter.addOutput("by_product", byProduct.toString());

        // Three rankings over the same aggregated rows.
        String[][] rankings = {
                {"rank-revenue", "ranked_by_net_revenue", String.valueOf(FINAL_NET_REVENUE_COLUMN)},
                {"rank-quantity", "ranked_by_quantity_sold", String.valueOf(FINAL_QTY_SOLD_COLUMN)},
                {"rank-returns", "ranked_by_quantity_returned", String.valueOf(FINAL_QTY_RETURNED_COLUMN)},
        };
        for (String[] ranking : rankings) {
            Path output = new Path(resultDir, ranking[1]);
            Job rank = newJob(ranking[0]);
            RankStage.configure(rank, Integer.parseInt(ranking[2]), true,
                    getConf().getInt("cartscope.rank.limit.products", 0));
            addInput(rank, byProduct);
            setOutput(rank, output);
            if (!runStage(ranking[0], rank, List.of(byProduct.toString()), output)) {
                return false;
            }
            reporter.addOutput(ranking[1], output.toString());
        }
        return true;
    }

    // =====================================================================

    public static class ProductLineMapper extends Mapper<Object, Text, Text, Aggregate> {

        private final ValidatedRecord record = new ValidatedRecord();
        private final Text outKey = new Text();

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            if (!record.parse(value.toString())) {
                context.getCounter(Stat.MALFORMED_VALIDATED_RECORDS).increment(1L);
                return;
            }

            Aggregate metrics = Aggregate.zeros(L_WIDTH);
            if (record.isSale()) {
                metrics.set(L_GROSS, record.lineValue());
                metrics.set(L_QTY_SOLD, record.quantity());
                metrics.set(L_SALE_LINES, 1.0d);
            } else {
                metrics.set(L_RETURNS, record.absValue());
                metrics.set(L_QTY_RETURNED, Math.abs(record.quantity()));
                metrics.set(L_RETURN_LINES, 1.0d);
            }
            metrics.setLabel(record.description());

            outKey.set(record.stockCode() + "\t" + record.invoiceNo());
            context.write(outKey, metrics);
        }
    }

    /** Collapses a product's lines on one invoice and re-keys by stock code. */
    public static class ProductInvoiceReducer
            extends Reducer<Text, Aggregate, Text, Aggregate> {

        private final Text stockKey = new Text();

        @Override
        protected void reduce(Text stockAndInvoice, Iterable<Aggregate> lines, Context context)
                throws IOException, InterruptedException {
            Aggregate group = Aggregate.zeros(L_WIDTH);
            for (Aggregate line : lines) {
                group.merge(line);
            }

            Aggregate out = Aggregate.zeros(P_WIDTH);
            for (int i = 0; i < L_WIDTH; i++) {
                out.set(i, group.get(i));
            }
            out.set(P_INVOICES, 1.0d);
            out.setLabel(group.label());

            String key = stockAndInvoice.toString();
            stockKey.set(key.substring(0, key.indexOf('\t')));
            context.getCounter(Stat.PRODUCT_INVOICE_GROUPS).increment(1L);
            context.write(stockKey, out);
        }
    }

    /**
     * Produces the reported product row.
     *
     * <p>Output columns, tab separated:
     * {@code stock_code, gross_revenue, returns, net_revenue, quantity_sold,
     * quantity_returned, distinct_invoices, sale_lines, return_lines,
     * description}. The description is last because it is the only free text
     * column.
     */
    public static class ProductRollupReducer extends Reducer<Text, Aggregate, Text, Text> {

        private final Text out = new Text();

        @Override
        protected void reduce(Text stockCode, Iterable<Aggregate> invoices, Context context)
                throws IOException, InterruptedException {
            Aggregate totals = Aggregate.zeros(P_WIDTH);
            for (Aggregate invoice : invoices) {
                totals.merge(invoice);
            }

            double gross = CustomerSpendingJob.round2(totals.get(L_GROSS));
            double returns = CustomerSpendingJob.round2(totals.get(L_RETURNS));
            long quantityReturned = totals.getLong(L_QTY_RETURNED);
            if (quantityReturned > 0L) {
                context.getCounter(Stat.PRODUCTS_WITH_RETURNS).increment(1L);
            }
            context.getCounter(Stat.PRODUCTS_REPORTED).increment(1L);

            String description = totals.label();
            out.set(gross
                    + "\t" + returns
                    + "\t" + CustomerSpendingJob.round2(gross - returns)
                    + "\t" + totals.getLong(L_QTY_SOLD)
                    + "\t" + quantityReturned
                    + "\t" + totals.getLong(P_INVOICES)
                    + "\t" + totals.getLong(L_SALE_LINES)
                    + "\t" + totals.getLong(L_RETURN_LINES)
                    + "\t" + (description.isEmpty() ? "(no description)" : description));
            context.write(stockCode, out);
        }
    }
}
