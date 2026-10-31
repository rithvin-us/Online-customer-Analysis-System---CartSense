package com.cartscope.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import com.cartscope.jobs.support.ProductClass;
import com.cartscope.util.RetailSchema;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.util.ToolRunner;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Runs the whole {@code product_analysis} chain — all seven jobs — on Hadoop's
 * {@code LocalJobRunner} over a catalogue small enough to check by hand.
 *
 * <h2>Why this test exists</h2>
 * The classification stages produce figures that are only correct <em>in
 * relation to each other</em>: a cumulative share has to end at 100%, a band's
 * products have to add up to the catalogue, and an ABC class has to follow from
 * the cumulative share printed next to it. A unit test of the band rules cannot
 * see any of that, because every one of those properties is a property of the
 * shuffle and of the order the single reducer walks the catalogue in.
 *
 * <p>This runs real mappers, a real shuffle and real reducers. It is not a
 * substitute for {@code make test-e2e}, which runs the same code on the real
 * cluster against the real dataset; it is what makes the arithmetic checkable
 * without one.
 *
 * <h2>The catalogue</h2>
 * Five stock codes, with figures chosen so every total is exact in decimal:
 *
 * <pre>
 *   code  sales                      returns        gross    qty  invoices
 *   A1    100 @ 8.00, 100 @ 8.00     —              1600.00  200  2
 *   B1     50 @ 4.00                 10 @ 4.00       200.00   50  2
 *   E1      2 @ 50.00                —               100.00    2  1
 *   C1X     5 @ 0.50                 —                 2.50    5  1
 *   D1    —                           3 @ 10.00         0.00    0  1
 * </pre>
 *
 * Gross revenue of the <em>sold</em> catalogue is 1902.50. D1 never sold, so it
 * is excluded from the classification and counted instead.
 */
class ProductPipelineLocalTest {

    private static final double SOLD_CATALOGUE_GROSS = 1902.50d;

    @TempDir
    Path tmp;

    @Test
    void theChainClassifiesACatalogueConsistently() throws Exception {
        Path input = tmp.resolve("validated");
        Files.createDirectories(input);
        Files.write(input.resolve("part-r-00000"), catalogue(), StandardCharsets.UTF_8);

        Path work = tmp.resolve("work");
        Path result = tmp.resolve("result");

        Configuration conf = new Configuration();
        conf.set("fs.defaultFS", "file:///");
        conf.set("mapreduce.framework.name", "local");
        conf.set("mapreduce.jobtracker.address", "local");
        conf.set("mapreduce.cluster.local.dir", tmp.resolve("mr-local").toString());
        conf.set("yarn.app.mapreduce.am.staging-dir", tmp.resolve("staging").toString());
        // LocalJobRunner runs one reducer; saying so keeps the chain honest
        // about what it was given rather than silently disagreeing with it.
        conf.setInt("cartscope.reducers", 1);

        int exit = ToolRunner.run(conf, new ProductPopularityJob(), new String[] {
            "--input", input.toString(),
            "--work", work.toString(),
            "--output", result.toString(),
            "--run-id", "local-test",
        });
        assertEquals(0, exit, "the product analysis chain should have succeeded");

        // -- by_product: every stock code, including the one that never sold.
        List<String[]> products = rows(result.resolve("by_product"));
        assertEquals(5, products.size());
        for (String[] row : products) {
            assertEquals(10, row.length, "by_product row width");
        }

        // -- classified_products: the sold catalogue, in revenue order.
        List<String[]> classified = rows(result.resolve("classified_products"));
        assertEquals(4, classified.size(), "D1 never sold, so it is not classified");
        for (String[] row : classified) {
            assertEquals(16, row.length, "classified_products row width");
        }

        assertEquals(List.of("A1", "B1", "E1", "C1X"),
                classified.stream().map(row -> row[1]).toList(),
                "descending gross revenue");
        assertEquals(List.of("1", "2", "3", "4"),
                classified.stream().map(row -> row[0]).toList(),
                "the rank is 1-based and gapless");

        // Shares and the classes read off them, checked against the hand
        // arithmetic in the class comment.
        assertEquals(1600.00d, Double.parseDouble(classified.get(0)[2]), 1e-9d);
        assertEquals(100.0d * 1600.00d / SOLD_CATALOGUE_GROSS,
                Double.parseDouble(classified.get(0)[9]), 0.01d, "A1's revenue share");
        assertEquals(List.of(
                ProductClass.CLASS_A, ProductClass.CLASS_B,
                ProductClass.CLASS_B, ProductClass.CLASS_C),
                classified.stream().map(row -> row[11]).toList(),
                "ABC follows the cumulative share");

        // The cumulative share rises monotonically and finishes at 100%.
        double previous = 0.0d;
        for (String[] row : classified) {
            double cumulative = Double.parseDouble(row[10]);
            assertTrue(cumulative >= previous,
                    "cumulative share fell at rank " + row[0] + ": " + cumulative);
            previous = cumulative;
        }
        assertEquals(100.0d, previous, 0.01d, "the last product completes the catalogue");

        // Per-product figures: average unit price, bands, return rate.
        assertEquals(8.00d, Double.parseDouble(classified.get(0)[7]), 1e-9d);
        assertEquals("5.00 to 9.99", classified.get(0)[12]);
        assertEquals("200 to 999 units", classified.get(0)[13]);
        assertEquals("No returns", classified.get(0)[14]);
        assertEquals("GOLD WIDGET", classified.get(0)[15]);

        // B1: 10 of the 60 units it handled came back.
        assertEquals(100.0d * 10 / 60, Double.parseDouble(classified.get(1)[8]), 0.01d);
        assertEquals("High (over 10%)", classified.get(1)[14]);
        assertEquals("25.00 and over", classified.get(2)[12], "E1 sold at 50.00");
        assertEquals("Under 1.00", classified.get(3)[12], "C1X sold at 0.50");

        // -- by_classification: four dimensions over the same four products.
        List<String[]> bands = rows(result.resolve("by_classification"));
        for (String[] row : bands) {
            assertEquals(11, row.length, "by_classification row width");
        }

        Map<String, List<String[]>> byDimension = new LinkedHashMap<>();
        for (String[] row : bands) {
            byDimension.computeIfAbsent(row[0], dimension -> new ArrayList<>()).add(row);
        }
        assertEquals(java.util.Set.of(
                ProductClass.DIM_ABC, ProductClass.DIM_PRICE,
                ProductClass.DIM_VOLUME, ProductClass.DIM_RETURNS),
                byDimension.keySet());

        for (Map.Entry<String, List<String[]>> dimension : byDimension.entrySet()) {
            long products_ = 0L;
            double revenueShare = 0.0d;
            double gross = 0.0d;
            double productShare = 0.0d;
            int lastOrdinal = 0;
            for (String[] row : dimension.getValue()) {
                int ordinal = Integer.parseInt(row[2]);
                assertTrue(ordinal >= lastOrdinal,
                        dimension.getKey() + " bands are out of reporting order");
                lastOrdinal = ordinal;
                assertTrue(ordinal > 0, "every emitted band has a position");
                products_ += Long.parseLong(row[3]);
                productShare += Double.parseDouble(row[4]);
                gross += Double.parseDouble(row[7]);
                revenueShare += Double.parseDouble(row[9]);
            }
            assertEquals(4L, products_, dimension.getKey() + " covers every sold product once");
            assertEquals(100.0d, productShare, 0.05d, dimension.getKey() + " product shares");
            assertEquals(100.0d, revenueShare, 0.05d, dimension.getKey() + " revenue shares");
            assertEquals(SOLD_CATALOGUE_GROSS, gross, 0.01d,
                    dimension.getKey() + " accounts for the whole sold catalogue");
        }

        assertEquals(1L, bandProducts(bands, ProductClass.DIM_ABC, "A"));
        assertEquals(2L, bandProducts(bands, ProductClass.DIM_ABC, "B"));
        assertEquals(1L, bandProducts(bands, ProductClass.DIM_ABC, "C"));
        assertEquals(2L, bandProducts(bands, ProductClass.DIM_VOLUME, "1 to 9 units"));
        assertEquals(3L, bandProducts(bands, ProductClass.DIM_RETURNS, "No returns"));
        assertEquals(1L, bandProducts(bands, ProductClass.DIM_RETURNS, "High (over 10%)"));
        // A band nothing fell into is absent rather than reported as a zero row.
        assertEquals(-1L, bandProducts(bands, ProductClass.DIM_VOLUME, "5000 units and over"));

        // -- the reach ranking: orders the product appeared on, not units.
        List<String[]> reach = rows(result.resolve("ranked_by_distinct_invoices"));
        assertEquals(5, reach.size());
        assertEquals(11, reach.get(0).length, "ranked row width");
        assertEquals(2L, Long.parseLong(reach.get(0)[7]), "the widest reach is 2 orders");
        assertFalse(reach.get(reach.size() - 1)[7].isEmpty());
    }

    /** Products in one band, or -1 when the band was not written at all. */
    private static long bandProducts(List<String[]> bands, String dimension, String band) {
        for (String[] row : bands) {
            if (row[0].equals(dimension) && row[1].equals(band)) {
                return Long.parseLong(row[3]);
            }
        }
        return -1L;
    }

    /** Reads the {@code part-*} files of a stage output into split rows. */
    private static List<String[]> rows(Path directory) throws IOException {
        List<String[]> rows = new ArrayList<>();
        try (Stream<Path> files = Files.list(directory)) {
            for (Path file : files.filter(path -> path.getFileName().toString().startsWith("part"))
                    .sorted().toList()) {
                for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
                    if (!line.isEmpty()) {
                        rows.add(line.split("\t", -1));
                    }
                }
            }
        }
        return rows;
    }

    private static List<String> catalogue() {
        List<String> lines = new ArrayList<>();
        lines.add(sale("I1", "A1", "GOLD WIDGET", 100, 8.00d));
        lines.add(sale("I2", "A1", "GOLD WIDGET", 100, 8.00d));
        lines.add(sale("I1", "B1", "SILVER WIDGET", 50, 4.00d));
        lines.add(reversal("C1", "B1", "SILVER WIDGET", 10, 4.00d));
        lines.add(sale("I4", "E1", "LUXURY ITEM", 2, 50.00d));
        lines.add(sale("I3", "C1X", "TIN TOY", 5, 0.50d));
        lines.add(reversal("C2", "D1", "RETURN ONLY", 3, 10.00d));
        return lines;
    }

    private static String sale(String invoice, String stockCode, String description,
            long quantity, double unitPrice) {
        return record(invoice, stockCode, description, quantity, unitPrice,
                quantity * unitPrice, RetailSchema.CLASS_SALE);
    }

    private static String reversal(String invoice, String stockCode, String description,
            long quantity, double unitPrice) {
        return record(invoice, stockCode, description, -quantity, unitPrice,
                -(quantity * unitPrice), RetailSchema.CLASS_RETURN);
    }

    /** One canonical validated record, in the layout {@code ValidationJob} writes. */
    private static String record(String invoice, String stockCode, String description,
            long quantity, double unitPrice, double lineValue, String txnClass) {
        return String.join("\t",
                invoice,
                stockCode,
                description,
                Long.toString(quantity),
                "1291000000000",
                "2010-11-29 09:00:00",
                "2010-11",
                Double.toString(unitPrice),
                "17850",
                "United Kingdom",
                Double.toString(lineValue),
                Double.toString(Math.abs(lineValue)),
                txnClass);
    }
}
