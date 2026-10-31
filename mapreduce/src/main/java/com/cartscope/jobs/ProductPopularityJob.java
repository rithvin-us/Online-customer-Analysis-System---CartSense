package com.cartscope.jobs;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.cartscope.io.Aggregate;
import com.cartscope.io.AggregateSumReducer;
import com.cartscope.jobs.support.KeyedAggregateMapper;
import com.cartscope.jobs.support.ProductClass;
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
 *   <li><b>rank-revenue</b>, <b>rank-quantity</b>, <b>rank-returns</b>,
 *       <b>rank-reach</b> — four orderings of the same rows. The top ten by
 *       revenue, by units sold, by returned units and by the number of orders
 *       the product appeared on are the first ten rows of these four
 *       files.</li>
 *   <li><b>classify</b> — the classification stage. Products that actually
 *       sold are put in descending revenue order and given an ABC (Pareto)
 *       class, a price band, a volume band and a return class, together with
 *       the cumulative revenue share that the ABC class is read from.</li>
 *   <li><b>band-summary</b> — how many products, units and pounds sit in each
 *       band of each of those four classifications.</li>
 * </ol>
 *
 * <h2>Why the classification needs its own stage</h2>
 * A band boundary on one product's own figures (its price, its volume) could in
 * principle be applied in the roll-up reducer. The ABC class cannot: it is a
 * property of where the product sits in the <em>whole</em> catalogue's revenue
 * distribution, which no reducer handling a single product can know. The
 * classify stage therefore runs with a single reducer that walks the catalogue
 * in revenue order, exactly as the RFM scoring stage walks the customer
 * population — see {@link RfmAnalysisJob} for the note on what that costs and
 * what it would take at a larger scale.
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
    private static final int FINAL_GROSS_REVENUE_COLUMN = 1;
    private static final int FINAL_NET_REVENUE_COLUMN = 3;
    private static final int FINAL_QTY_SOLD_COLUMN = 4;
    private static final int FINAL_QTY_RETURNED_COLUMN = 5;
    private static final int FINAL_DISTINCT_INVOICES_COLUMN = 6;
    private static final int FINAL_DESCRIPTION_COLUMN = 9;
    /** Number of columns in a {@code by_product} row. */
    private static final int FINAL_WIDTH = 10;

    // Band summary metric slots.
    private static final int B_PRODUCTS = 0;
    private static final int B_QTY_SOLD = 1;
    private static final int B_QTY_RETURNED = 2;
    private static final int B_GROSS = 3;
    private static final int B_NET = 4;
    private static final int B_WIDTH = 5;

    /** Folding key for the stage that must see every product at once. */
    private static final String ALL_KEY = "ALL";

    public enum Stat {
        MALFORMED_VALIDATED_RECORDS,
        PRODUCT_INVOICE_GROUPS,
        PRODUCTS_REPORTED,
        PRODUCTS_WITH_RETURNS,
        MALFORMED_PRODUCT_ROWS,
        PRODUCTS_CLASSIFIED,
        PRODUCTS_NEVER_SOLD_EXCLUDED,
        CLASS_A_PRODUCTS,
        CLASS_B_PRODUCTS,
        CLASS_C_PRODUCTS,
        BAND_SUMMARY_ROWS
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
                {"rank-reach", "ranked_by_distinct_invoices",
                        String.valueOf(FINAL_DISTINCT_INVOICES_COLUMN)},
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

        Path classified = new Path(resultDir, "classified_products");
        Job classifyJob = newJob("classify");
        classifyJob.setMapperClass(SoldProductMapper.class);
        // No combiner: the ABC class depends on a product's position in the
        // catalogue's revenue distribution, so there is nothing a partial
        // aggregation on the map side could usefully fold.
        classifyJob.setReducerClass(ClassificationReducer.class);
        classifyJob.setNumReduceTasks(1);
        classifyJob.setMapOutputKeyClass(Text.class);
        classifyJob.setMapOutputValueClass(Text.class);
        classifyJob.setOutputKeyClass(Text.class);
        classifyJob.setOutputValueClass(Text.class);
        addInput(classifyJob, byProduct);
        setOutput(classifyJob, classified);
        if (!runStage("classify", classifyJob, List.of(byProduct.toString()), classified)) {
            return false;
        }
        reporter.addOutput("classified_products", classified.toString());

        Path byClassification = new Path(resultDir, "by_classification");
        Job summaryJob = newJob("band-summary");
        summaryJob.setMapperClass(BandMapper.class);
        summaryJob.setCombinerClass(AggregateSumReducer.class);
        summaryJob.setReducerClass(BandSummaryReducer.class);
        // One reducer: a band's share of the catalogue is a fraction of a
        // total that no single band's group can see.
        summaryJob.setNumReduceTasks(1);
        summaryJob.setMapOutputKeyClass(Text.class);
        summaryJob.setMapOutputValueClass(Aggregate.class);
        summaryJob.setOutputKeyClass(Text.class);
        summaryJob.setOutputValueClass(Text.class);
        addInput(summaryJob, classified);
        setOutput(summaryJob, byClassification);
        if (!runStage("band-summary", summaryJob, List.of(classified.toString()), byClassification)) {
            return false;
        }
        reporter.addOutput("by_classification", byClassification.toString());
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

    // =====================================================================
    // Stage 6: classify
    // =====================================================================

    /**
     * Passes on the products that were <em>actually sold</em>, folded into one
     * group.
     *
     * <p>A stock code that only ever appeared on reversal lines has no selling
     * price, no sold volume and no revenue to contribute. It is counted through
     * {@code PRODUCTS_NEVER_SOLD_EXCLUDED} and left out, rather than classified
     * against figures it does not have. It remains in {@code by_product} and in
     * the return ranking, which is where it belongs.
     */
    public static class SoldProductMapper extends Mapper<Object, Text, Text, Text> {

        private final Text all = new Text(ALL_KEY);

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            String line = value.toString();
            if (line.isEmpty()) {
                return;
            }
            String[] fields = line.split("\t", -1);
            if (fields.length < FINAL_WIDTH) {
                context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                return;
            }
            double gross;
            long quantitySold;
            try {
                gross = Double.parseDouble(fields[FINAL_GROSS_REVENUE_COLUMN]);
                quantitySold = Math.round(Double.parseDouble(fields[FINAL_QTY_SOLD_COLUMN]));
            } catch (NumberFormatException notANumber) {
                context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                return;
            }
            if (quantitySold <= 0L || gross <= 0.0d) {
                context.getCounter(Stat.PRODUCTS_NEVER_SOLD_EXCLUDED).increment(1L);
                return;
            }
            context.write(all, value);
        }
    }

    /**
     * Ranks the sold catalogue by revenue and classifies every product in it.
     *
     * <p>Output columns, tab separated: {@code rank, stock_code, gross_revenue,
     * net_revenue, quantity_sold, quantity_returned, distinct_invoices,
     * average_unit_price, return_rate_pct, revenue_share_pct,
     * cumulative_revenue_share_pct, abc_class, price_band, volume_band,
     * return_class, description}.
     *
     * <p>Shares are taken over <b>gross</b> revenue, not net. A cumulative
     * share has to be monotonic to mean anything, and net revenue is negative
     * for a product whose returns in the loaded period outweigh its sales, so a
     * cumulative net share could fall as it went down the ranking. Net revenue
     * is reported on every row next to the gross figure the shares are built
     * from, so neither is hidden.
     */
    public static class ClassificationReducer extends Reducer<Text, Text, Text, Text> {

        private static final class Product {
            private String stockCode = "";
            private String description = "";
            private double gross;
            private double net;
            private long quantitySold;
            private long quantityReturned;
            private long distinctInvoices;
        }

        private final Text outKey = new Text();
        private final Text out = new Text();

        @Override
        protected void reduce(Text all, Iterable<Text> rows, Context context)
                throws IOException, InterruptedException {
            List<Product> products = new ArrayList<>();
            double totalGross = 0.0d;

            for (Text row : rows) {
                String[] fields = row.toString().split("\t", -1);
                if (fields.length < FINAL_WIDTH) {
                    context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                    continue;
                }
                Product product = new Product();
                try {
                    product.gross = Double.parseDouble(fields[FINAL_GROSS_REVENUE_COLUMN]);
                    product.net = Double.parseDouble(fields[FINAL_NET_REVENUE_COLUMN]);
                    product.quantitySold =
                            Math.round(Double.parseDouble(fields[FINAL_QTY_SOLD_COLUMN]));
                    product.quantityReturned =
                            Math.round(Double.parseDouble(fields[FINAL_QTY_RETURNED_COLUMN]));
                    product.distinctInvoices =
                            Math.round(Double.parseDouble(fields[FINAL_DISTINCT_INVOICES_COLUMN]));
                } catch (NumberFormatException notANumber) {
                    context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                    continue;
                }
                product.stockCode = fields[0];
                product.description = fields[FINAL_DESCRIPTION_COLUMN];
                totalGross += product.gross;
                products.add(product);
            }

            if (products.isEmpty() || totalGross <= 0.0d) {
                return;
            }

            // Descending gross revenue, ties broken by stock code. The tie
            // break is what makes the rank — and therefore every class read
            // off it — identical between two runs over the same data.
            products.sort(Comparator.comparingDouble((Product product) -> product.gross)
                    .reversed()
                    .thenComparing(product -> product.stockCode));

            double cumulative = 0.0d;
            long rank = 0L;
            for (Product product : products) {
                double shareBefore = cumulative * 100.0d / totalGross;
                cumulative += product.gross;
                double cumulativeShare = cumulative * 100.0d / totalGross;
                double share = product.gross * 100.0d / totalGross;

                double averagePrice =
                        ProductClass.averageUnitPrice(product.gross, product.quantitySold);
                double returnRate = ProductClass.returnRatePercent(
                        product.quantitySold, product.quantityReturned);
                ProductClass.Band abc = ProductClass.abcClass(shareBefore);
                ProductClass.Band priceBand = ProductClass.priceBand(averagePrice);
                ProductClass.Band volumeBand = ProductClass.volumeBand(product.quantitySold);
                ProductClass.Band returnClass =
                        ProductClass.returnClass(product.quantityReturned, returnRate);

                switch (abc.label()) {
                    case ProductClass.CLASS_A ->
                            context.getCounter(Stat.CLASS_A_PRODUCTS).increment(1L);
                    case ProductClass.CLASS_B ->
                            context.getCounter(Stat.CLASS_B_PRODUCTS).increment(1L);
                    default -> context.getCounter(Stat.CLASS_C_PRODUCTS).increment(1L);
                }
                context.getCounter(Stat.PRODUCTS_CLASSIFIED).increment(1L);

                rank++;
                outKey.set(Long.toString(rank));
                out.set(product.stockCode
                        + "\t" + CustomerSpendingJob.round2(product.gross)
                        + "\t" + CustomerSpendingJob.round2(product.net)
                        + "\t" + product.quantitySold
                        + "\t" + product.quantityReturned
                        + "\t" + product.distinctInvoices
                        + "\t" + CustomerSpendingJob.round2(averagePrice)
                        + "\t" + CustomerSpendingJob.round2(returnRate)
                        + "\t" + CustomerSpendingJob.round2(share)
                        + "\t" + CustomerSpendingJob.round2(cumulativeShare)
                        + "\t" + abc.label()
                        + "\t" + priceBand.label()
                        + "\t" + volumeBand.label()
                        + "\t" + returnClass.label()
                        + "\t" + product.description);
                context.write(outKey, out);
            }
        }
    }

    // =====================================================================
    // Stage 7: band-summary
    // =====================================================================

    /**
     * Keys each classified product by every band it belongs to, once per
     * classification dimension.
     *
     * <p>The band's ordinal is part of the key, so the shuffle sorts the bands
     * into their reporting order — dimension first, then position within the
     * dimension — and the reporter never has to decide that "25.00 and over"
     * comes after "Under 1.00".
     */
    public static class BandMapper extends Mapper<Object, Text, Text, Aggregate> {

        private static final int C_GROSS = 2;
        private static final int C_NET = 3;
        private static final int C_QTY_SOLD = 4;
        private static final int C_QTY_RETURNED = 5;
        private static final int C_ABC = 11;
        private static final int C_PRICE_BAND = 12;
        private static final int C_VOLUME_BAND = 13;
        private static final int C_RETURN_CLASS = 14;
        private static final int C_WIDTH = 16;

        private final Text outKey = new Text();

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            String line = value.toString();
            if (line.isEmpty()) {
                return;
            }
            String[] fields = line.split("\t", -1);
            if (fields.length < C_WIDTH) {
                context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                return;
            }

            Aggregate metrics = Aggregate.zeros(B_WIDTH);
            try {
                metrics.set(B_PRODUCTS, 1.0d);
                metrics.set(B_QTY_SOLD, Double.parseDouble(fields[C_QTY_SOLD]));
                metrics.set(B_QTY_RETURNED, Double.parseDouble(fields[C_QTY_RETURNED]));
                metrics.set(B_GROSS, Double.parseDouble(fields[C_GROSS]));
                metrics.set(B_NET, Double.parseDouble(fields[C_NET]));
            } catch (NumberFormatException notANumber) {
                context.getCounter(Stat.MALFORMED_PRODUCT_ROWS).increment(1L);
                return;
            }

            emit(context, ProductClass.DIM_ABC, fields[C_ABC], metrics);
            emit(context, ProductClass.DIM_PRICE, fields[C_PRICE_BAND], metrics);
            emit(context, ProductClass.DIM_VOLUME, fields[C_VOLUME_BAND], metrics);
            emit(context, ProductClass.DIM_RETURNS, fields[C_RETURN_CLASS], metrics);
        }

        private void emit(Context context, String dimension, String band, Aggregate metrics)
                throws IOException, InterruptedException {
            outKey.set(dimension
                    + "\t" + String.format("%02d", ProductClass.ordinalOf(dimension, band))
                    + "\t" + band);
            context.write(outKey, metrics);
        }
    }

    /**
     * One row per band: how much of the catalogue it holds.
     *
     * <p>Output columns, tab separated: {@code dimension, band, ordinal,
     * products, product_share_pct, quantity_sold, quantity_returned,
     * gross_revenue, net_revenue, revenue_share_pct, average_unit_price}.
     *
     * <p>A share is a fraction of a dimension's total, and no single band's
     * reduce group can see that total. The bands are therefore held until the
     * groups are exhausted and written in {@link #cleanup}. What is held is one
     * short row per band — at most a few dozen for the whole catalogue,
     * whatever the size of the dataset — and because the shuffle delivered the
     * keys in order, writing them out in the order they were received keeps the
     * bands in their reporting order.
     */
    public static class BandSummaryReducer extends Reducer<Text, Aggregate, Text, Text> {

        private static final class BandTotals {
            private String dimension = "";
            private String band = "";
            private int ordinal;
            private long products;
            private long quantitySold;
            private long quantityReturned;
            private double gross;
            private double net;
        }

        private final List<BandTotals> bands = new ArrayList<>();
        private final Text outKey = new Text();
        private final Text out = new Text();

        @Override
        protected void reduce(Text key, Iterable<Aggregate> values, Context context) {
            String[] parts = key.toString().split("\t", -1);
            if (parts.length < 3) {
                return;
            }
            Aggregate totals = Aggregate.zeros(B_WIDTH);
            for (Aggregate value : values) {
                totals.merge(value);
            }

            BandTotals band = new BandTotals();
            band.dimension = parts[0];
            try {
                band.ordinal = Integer.parseInt(parts[1]);
            } catch (NumberFormatException notANumber) {
                band.ordinal = 0;
            }
            band.band = parts[2];
            band.products = totals.getLong(B_PRODUCTS);
            band.quantitySold = totals.getLong(B_QTY_SOLD);
            band.quantityReturned = totals.getLong(B_QTY_RETURNED);
            band.gross = totals.get(B_GROSS);
            band.net = totals.get(B_NET);
            bands.add(band);
        }

        @Override
        protected void cleanup(Context context) throws IOException, InterruptedException {
            Map<String, double[]> dimensionTotals = new LinkedHashMap<>();
            for (BandTotals band : bands) {
                double[] total = dimensionTotals.computeIfAbsent(
                        band.dimension, dimension -> new double[2]);
                total[0] += band.products;
                total[1] += band.gross;
            }

            for (BandTotals band : bands) {
                double[] total = dimensionTotals.get(band.dimension);
                double productShare = total[0] > 0.0d ? band.products * 100.0d / total[0] : 0.0d;
                double revenueShare = total[1] > 0.0d ? band.gross * 100.0d / total[1] : 0.0d;
                double averagePrice = ProductClass.averageUnitPrice(band.gross, band.quantitySold);

                outKey.set(band.dimension);
                out.set(band.band
                        + "\t" + band.ordinal
                        + "\t" + band.products
                        + "\t" + CustomerSpendingJob.round2(productShare)
                        + "\t" + band.quantitySold
                        + "\t" + band.quantityReturned
                        + "\t" + CustomerSpendingJob.round2(band.gross)
                        + "\t" + CustomerSpendingJob.round2(band.net)
                        + "\t" + CustomerSpendingJob.round2(revenueShare)
                        + "\t" + CustomerSpendingJob.round2(averagePrice));
                context.write(outKey, out);
                context.getCounter(Stat.BAND_SUMMARY_ROWS).increment(1L);
            }
        }
    }
}
