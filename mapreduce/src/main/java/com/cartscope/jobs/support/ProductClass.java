package com.cartscope.jobs.support;

/**
 * The product classification rules: the bands and classes a sold product is
 * placed in by the {@code classify} stage of the product analysis.
 *
 * <p>Every rule here is a <em>pure function of one aggregated figure</em>, with
 * fixed, published boundaries. That is deliberate, and it is the difference
 * between a classification and a guess:
 *
 * <ul>
 *   <li>the boundaries are stated in {@code docs/BUSINESS_RULES.md} and can be
 *       checked by hand against any row of the result;</li>
 *   <li>nothing is fitted, learned or sampled, so two runs over the same data
 *       produce byte-identical classes;</li>
 *   <li>a band's ordinal is carried with it, so the reporting order of the
 *       bands is decided here and never re-derived in the browser.</li>
 * </ul>
 *
 * <p>Fixed money boundaries are used for the price bands rather than population
 * quintiles, because "what a shop charges for an item" is meaningful on its own
 * scale: a £0.85 item is a cheap item whichever other products were loaded
 * alongside it. The RFM scores take the opposite decision for the opposite
 * reason, and both are documented where they are made.
 */
public final class ProductClass {

    /** Dimension names, used as the first column of the band summary. */
    public static final String DIM_ABC = "abc_class";
    public static final String DIM_PRICE = "price_band";
    public static final String DIM_VOLUME = "volume_band";
    public static final String DIM_RETURNS = "return_class";

    public static final String CLASS_A = "A";
    public static final String CLASS_B = "B";
    public static final String CLASS_C = "C";

    /** A band: its reporting position, and the label that is written out. */
    public record Band(int ordinal, String label) {
    }

    private static final Band[] PRICE_BANDS = {
            new Band(1, "Under 1.00"),
            new Band(2, "1.00 to 2.49"),
            new Band(3, "2.50 to 4.99"),
            new Band(4, "5.00 to 9.99"),
            new Band(5, "10.00 to 24.99"),
            new Band(6, "25.00 and over"),
    };

    private static final Band[] VOLUME_BANDS = {
            new Band(1, "1 to 9 units"),
            new Band(2, "10 to 49 units"),
            new Band(3, "50 to 199 units"),
            new Band(4, "200 to 999 units"),
            new Band(5, "1000 to 4999 units"),
            new Band(6, "5000 units and over"),
    };

    private static final Band[] RETURN_CLASSES = {
            new Band(1, "No returns"),
            new Band(2, "Low (under 2%)"),
            new Band(3, "Moderate (2% to 10%)"),
            new Band(4, "High (over 10%)"),
    };

    private static final Band[] ABC_CLASSES = {
            new Band(1, CLASS_A),
            new Band(2, CLASS_B),
            new Band(3, CLASS_C),
    };

    private ProductClass() {
    }

    /**
     * Average realised unit price: the money actually taken for the product
     * divided by the units actually sold.
     *
     * <p>This is not the {@code UnitPrice} column. One stock code is sold at
     * several prices in the source data, so the only unit price that can be
     * reported for a product without picking one line arbitrarily is the one
     * its own sales imply.
     *
     * @return 0 when no units were sold, rather than a division by zero
     */
    public static double averageUnitPrice(double grossRevenue, long quantitySold) {
        return quantitySold > 0L ? grossRevenue / quantitySold : 0.0d;
    }

    /**
     * Share of the units handled for this product that came back, as a
     * percentage.
     *
     * <p>Returned units are divided by sold <em>plus</em> returned units rather
     * than by sold units alone. That keeps the figure inside 0 to 100 even for
     * a product whose returns in the loaded period belong to sales made before
     * it, which a plain returned/sold ratio would report as more than 100%.
     *
     * @return 0 when the product has no units at all
     */
    public static double returnRatePercent(long quantitySold, long quantityReturned) {
        long handled = quantitySold + quantityReturned;
        return handled > 0L ? (quantityReturned * 100.0d) / handled : 0.0d;
    }

    /** Band of a product's average realised unit price. */
    public static Band priceBand(double averageUnitPrice) {
        if (averageUnitPrice < 1.0d) {
            return PRICE_BANDS[0];
        }
        if (averageUnitPrice < 2.5d) {
            return PRICE_BANDS[1];
        }
        if (averageUnitPrice < 5.0d) {
            return PRICE_BANDS[2];
        }
        if (averageUnitPrice < 10.0d) {
            return PRICE_BANDS[3];
        }
        if (averageUnitPrice < 25.0d) {
            return PRICE_BANDS[4];
        }
        return PRICE_BANDS[5];
    }

    /** Band of a product's sold volume, in units. */
    public static Band volumeBand(long quantitySold) {
        if (quantitySold < 10L) {
            return VOLUME_BANDS[0];
        }
        if (quantitySold < 50L) {
            return VOLUME_BANDS[1];
        }
        if (quantitySold < 200L) {
            return VOLUME_BANDS[2];
        }
        if (quantitySold < 1000L) {
            return VOLUME_BANDS[3];
        }
        if (quantitySold < 5000L) {
            return VOLUME_BANDS[4];
        }
        return VOLUME_BANDS[5];
    }

    /**
     * Return class of a product.
     *
     * @param quantityReturned returned units; zero is its own class, because
     *                         "never came back" is a different statement from
     *                         "came back rarely"
     * @param returnRatePercent as {@link #returnRatePercent}
     */
    public static Band returnClass(long quantityReturned, double returnRatePercent) {
        if (quantityReturned <= 0L) {
            return RETURN_CLASSES[0];
        }
        if (returnRatePercent < 2.0d) {
            return RETURN_CLASSES[1];
        }
        if (returnRatePercent <= 10.0d) {
            return RETURN_CLASSES[2];
        }
        return RETURN_CLASSES[3];
    }

    /**
     * ABC (Pareto) class, from the cumulative revenue share <em>reached before
     * this product was added</em>.
     *
     * <p>Taking the share before the product rather than after it is what makes
     * the rule well behaved at the boundary: the highest earning product is
     * always class A, even in a catalogue of one product where it alone is
     * 100% of revenue. Read aloud, the rule is "a product is A while the
     * products above it have not yet accounted for 80% of revenue".
     *
     * @param cumulativeShareBeforePercent 0 for the highest earning product
     */
    public static Band abcClass(double cumulativeShareBeforePercent) {
        if (cumulativeShareBeforePercent < 80.0d) {
            return ABC_CLASSES[0];
        }
        if (cumulativeShareBeforePercent < 95.0d) {
            return ABC_CLASSES[1];
        }
        return ABC_CLASSES[2];
    }

    /**
     * Reporting position of a band label within its dimension, so that a later
     * stage can re-key rows it reads back as text without inventing an order.
     *
     * @return the band's ordinal, or 0 for a label this class never emitted
     */
    public static int ordinalOf(String dimension, String label) {
        Band[] bands = switch (dimension) {
            case DIM_ABC -> ABC_CLASSES;
            case DIM_PRICE -> PRICE_BANDS;
            case DIM_VOLUME -> VOLUME_BANDS;
            case DIM_RETURNS -> RETURN_CLASSES;
            default -> new Band[0];
        };
        for (Band band : bands) {
            if (band.label().equals(label)) {
                return band.ordinal();
            }
        }
        return 0;
    }
}
