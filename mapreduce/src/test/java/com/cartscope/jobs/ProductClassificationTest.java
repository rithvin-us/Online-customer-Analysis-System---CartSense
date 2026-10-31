package com.cartscope.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.cartscope.jobs.support.ProductClass;
import org.junit.jupiter.api.Test;

/**
 * The product classification rules.
 *
 * <p>These are the boundaries published in {@code docs/BUSINESS_RULES.md}, so
 * the tests are written as the documented boundary cases: the value just below
 * a boundary and the boundary itself.
 */
class ProductClassificationTest {

    @Test
    void priceBandsSplitAtTheDocumentedBoundaries() {
        assertEquals("Under 1.00", ProductClass.priceBand(0.99d).label());
        assertEquals("1.00 to 2.49", ProductClass.priceBand(1.00d).label());
        assertEquals("1.00 to 2.49", ProductClass.priceBand(2.49d).label());
        assertEquals("2.50 to 4.99", ProductClass.priceBand(2.50d).label());
        assertEquals("5.00 to 9.99", ProductClass.priceBand(5.00d).label());
        assertEquals("10.00 to 24.99", ProductClass.priceBand(10.00d).label());
        assertEquals("25.00 and over", ProductClass.priceBand(25.00d).label());
        assertEquals("25.00 and over", ProductClass.priceBand(4_000.00d).label());
    }

    @Test
    void priceBandOrdinalsIncreaseWithPrice() {
        assertEquals(1, ProductClass.priceBand(0.5d).ordinal());
        assertEquals(6, ProductClass.priceBand(99.0d).ordinal());
        assertTrue(ProductClass.priceBand(3.0d).ordinal()
                < ProductClass.priceBand(30.0d).ordinal());
    }

    @Test
    void volumeBandsSplitAtTheDocumentedBoundaries() {
        assertEquals("1 to 9 units", ProductClass.volumeBand(1L).label());
        assertEquals("1 to 9 units", ProductClass.volumeBand(9L).label());
        assertEquals("10 to 49 units", ProductClass.volumeBand(10L).label());
        assertEquals("50 to 199 units", ProductClass.volumeBand(50L).label());
        assertEquals("200 to 999 units", ProductClass.volumeBand(999L).label());
        assertEquals("1000 to 4999 units", ProductClass.volumeBand(1_000L).label());
        assertEquals("5000 units and over", ProductClass.volumeBand(5_000L).label());
    }

    @Test
    void averageUnitPriceIsRevenueOverUnitsAndNeverDividesByZero() {
        assertEquals(2.5d, ProductClass.averageUnitPrice(250.0d, 100L), 1e-9d);
        assertEquals(0.0d, ProductClass.averageUnitPrice(250.0d, 0L), 1e-9d);
    }

    @Test
    void returnRateIsTheReturnedShareOfUnitsHandled() {
        // 10 of 110 units handled came back.
        assertEquals(100.0d * 10 / 110, ProductClass.returnRatePercent(100L, 10L), 1e-9d);
        assertEquals(0.0d, ProductClass.returnRatePercent(100L, 0L), 1e-9d);
        assertEquals(50.0d, ProductClass.returnRatePercent(5L, 5L), 1e-9d);
        // A product with no units at all is 0, not a division by zero.
        assertEquals(0.0d, ProductClass.returnRatePercent(0L, 0L), 1e-9d);
    }

    @Test
    void returnRateStaysWithinOneHundredPercent() {
        // More units came back in the loaded period than were sold in it.
        double rate = ProductClass.returnRatePercent(1L, 99L);
        assertTrue(rate <= 100.0d, "return rate should be a share of units handled: " + rate);
    }

    @Test
    void returnClassSeparatesNeverFromRarely() {
        assertEquals("No returns", ProductClass.returnClass(0L, 0.0d).label());
        assertEquals("Low (under 2%)", ProductClass.returnClass(1L, 1.99d).label());
        assertEquals("Moderate (2% to 10%)", ProductClass.returnClass(5L, 2.0d).label());
        assertEquals("Moderate (2% to 10%)", ProductClass.returnClass(5L, 10.0d).label());
        assertEquals("High (over 10%)", ProductClass.returnClass(50L, 10.01d).label());
    }

    @Test
    void abcClassIsReadFromTheShareReachedBeforeTheProduct() {
        // The highest earning product is always A, even when it alone is the
        // whole catalogue's revenue.
        assertEquals(ProductClass.CLASS_A, ProductClass.abcClass(0.0d).label());
        assertEquals(ProductClass.CLASS_A, ProductClass.abcClass(79.99d).label());
        assertEquals(ProductClass.CLASS_B, ProductClass.abcClass(80.0d).label());
        assertEquals(ProductClass.CLASS_B, ProductClass.abcClass(94.99d).label());
        assertEquals(ProductClass.CLASS_C, ProductClass.abcClass(95.0d).label());
        assertEquals(ProductClass.CLASS_C, ProductClass.abcClass(100.0d).label());
    }

    @Test
    void ordinalOfRecoversAPositionForEveryEmittedLabel() {
        assertEquals(1, ProductClass.ordinalOf(ProductClass.DIM_ABC, ProductClass.CLASS_A));
        assertEquals(3, ProductClass.ordinalOf(ProductClass.DIM_ABC, ProductClass.CLASS_C));
        assertEquals(ProductClass.priceBand(7.0d).ordinal(),
                ProductClass.ordinalOf(ProductClass.DIM_PRICE,
                        ProductClass.priceBand(7.0d).label()));
        assertEquals(ProductClass.volumeBand(500L).ordinal(),
                ProductClass.ordinalOf(ProductClass.DIM_VOLUME,
                        ProductClass.volumeBand(500L).label()));
        assertEquals(ProductClass.returnClass(3L, 5.0d).ordinal(),
                ProductClass.ordinalOf(ProductClass.DIM_RETURNS,
                        ProductClass.returnClass(3L, 5.0d).label()));
    }

    @Test
    void ordinalOfReportsZeroForAnythingItNeverEmitted() {
        assertEquals(0, ProductClass.ordinalOf(ProductClass.DIM_PRICE, "not a band"));
        assertEquals(0, ProductClass.ordinalOf("not a dimension", ProductClass.CLASS_A));
    }

    @Test
    void everyBandLabelIsFreeOfTabsSoItSurvivesTheStageFormat() {
        // Stage output is tab separated: a label with a tab in it would shift
        // every later column of the row.
        String[] labels = {
            ProductClass.priceBand(0.5d).label(),
            ProductClass.priceBand(30.0d).label(),
            ProductClass.volumeBand(5L).label(),
            ProductClass.volumeBand(9_000L).label(),
            ProductClass.returnClass(0L, 0.0d).label(),
            ProductClass.returnClass(9L, 40.0d).label(),
            ProductClass.abcClass(10.0d).label(),
        };
        for (String label : labels) {
            assertTrue(!label.isEmpty() && label.indexOf('\t') < 0 && label.indexOf('\n') < 0,
                    "unusable band label: " + label);
        }
    }
}
