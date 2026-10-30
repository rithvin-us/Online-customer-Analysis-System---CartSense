package com.cartscope.io;

import java.io.DataInput;
import java.io.DataOutput;
import java.io.IOException;
import java.util.Arrays;

import org.apache.hadoop.io.Writable;
import org.apache.hadoop.io.WritableUtils;

/**
 * The intermediate value type shared by every CartScope MapReduce job: a
 * vector of additive metrics, a vector of maximum-merged metrics, and one
 * optional text label.
 *
 * <p>Having a single value type is what makes {@link AggregateSumReducer}
 * reusable as a combiner for all of the jobs. Every one of the three merge
 * rules is associative, commutative and deterministic, which is precisely the
 * condition a combiner requires:
 *
 * <ul>
 *   <li>metrics are added element-wise;</li>
 *   <li>maxima are merged with {@code Math.max}. This exists for the RFM
 *       analysis, whose recency component is the <em>latest</em> purchase
 *       timestamp. A timestamp must never be summed, so it is kept in a
 *       separate vector that cannot accidentally be added;</li>
 *   <li>the label collapses to the lexicographically smallest non-empty value.
 *       That matters because a product's {@code Description} is not unique per
 *       {@code StockCode} in the source data: without a deterministic rule the
 *       displayed product name would depend on which combiner ran first.</li>
 * </ul>
 */
public class Aggregate implements Writable {

    private double[] metrics;
    private double[] maxima;
    private String label;

    public Aggregate() {
        this.metrics = new double[0];
        this.maxima = new double[0];
        this.label = "";
    }

    private Aggregate(double[] metrics, double[] maxima, String label) {
        this.metrics = metrics;
        this.maxima = maxima;
        this.label = label == null ? "" : label;
    }

    public static Aggregate of(double... metrics) {
        return new Aggregate(metrics.clone(), new double[0], "");
    }

    public static Aggregate labelled(String label, double... metrics) {
        return new Aggregate(metrics.clone(), new double[0], label);
    }

    /** A zero vector of {@code width} metrics, ready to accumulate into. */
    public static Aggregate zeros(int width) {
        return new Aggregate(new double[width], new double[0], "");
    }

    /** A zero vector with {@code maxWidth} additional maximum-merged slots. */
    public static Aggregate zeros(int width, int maxWidth) {
        return new Aggregate(new double[width], new double[maxWidth], "");
    }

    public int width() {
        return metrics.length;
    }

    public int maxWidth() {
        return maxima.length;
    }

    /** Value of maximum-merged slot {@code index}. */
    public double getMax(int index) {
        return index < maxima.length ? maxima[index] : Double.NEGATIVE_INFINITY;
    }

    public long getMaxLong(int index) {
        double value = getMax(index);
        return value == Double.NEGATIVE_INFINITY ? 0L : Math.round(value);
    }

    /** Sets maximum-merged slot {@code index}, growing the vector if needed. */
    public void setMax(int index, double value) {
        if (maxima.length < index + 1) {
            int previous = maxima.length;
            maxima = Arrays.copyOf(maxima, index + 1);
            Arrays.fill(maxima, previous, maxima.length, Double.NEGATIVE_INFINITY);
        }
        maxima[index] = value;
    }

    public double get(int index) {
        return index < metrics.length ? metrics[index] : 0.0d;
    }

    public long getLong(int index) {
        return Math.round(get(index));
    }

    public void set(int index, double value) {
        ensureWidth(index + 1);
        metrics[index] = value;
    }

    public String label() {
        return label;
    }

    public void setLabel(String value) {
        this.label = value == null ? "" : value;
    }

    /** Merges {@code other} into this instance in place. */
    public void merge(Aggregate other) {
        ensureWidth(other.metrics.length);
        for (int i = 0; i < other.metrics.length; i++) {
            metrics[i] += other.metrics[i];
        }
        for (int i = 0; i < other.maxima.length; i++) {
            if (other.maxima[i] > getMax(i)) {
                setMax(i, other.maxima[i]);
            }
        }
        String incoming = other.label;
        if (!incoming.isEmpty() && (label.isEmpty() || incoming.compareTo(label) < 0)) {
            label = incoming;
        }
    }

    public void reset(int width) {
        reset(width, 0);
    }

    public void reset(int width, int maxWidth) {
        if (metrics.length == width) {
            Arrays.fill(metrics, 0.0d);
        } else {
            metrics = new double[width];
        }
        if (maxima.length != maxWidth) {
            maxima = new double[maxWidth];
        }
        Arrays.fill(maxima, Double.NEGATIVE_INFINITY);
        label = "";
    }

    private void ensureWidth(int width) {
        if (metrics.length < width) {
            metrics = Arrays.copyOf(metrics, width);
        }
    }

    @Override
    public void write(DataOutput out) throws IOException {
        WritableUtils.writeVInt(out, metrics.length);
        for (double metric : metrics) {
            out.writeDouble(metric);
        }
        WritableUtils.writeVInt(out, maxima.length);
        for (double maximum : maxima) {
            out.writeDouble(maximum);
        }
        WritableUtils.writeString(out, label);
    }

    @Override
    public void readFields(DataInput in) throws IOException {
        int width = WritableUtils.readVInt(in);
        if (metrics.length != width) {
            metrics = new double[width];
        }
        for (int i = 0; i < width; i++) {
            metrics[i] = in.readDouble();
        }
        int maxWidth = WritableUtils.readVInt(in);
        if (maxima.length != maxWidth) {
            maxima = new double[maxWidth];
        }
        for (int i = 0; i < maxWidth; i++) {
            maxima[i] = in.readDouble();
        }
        label = WritableUtils.readString(in);
        if (label == null) {
            label = "";
        }
    }

    @Override
    public String toString() {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < metrics.length; i++) {
            if (i > 0) {
                out.append('\t');
            }
            out.append(metrics[i]);
        }
        for (double maximum : maxima) {
            out.append('\t');
            // A slot that never received a value serialises as 0 so that the
            // next stage can parse it as a number.
            out.append(maximum == Double.NEGATIVE_INFINITY ? 0.0d : maximum);
        }
        if (!label.isEmpty()) {
            out.append('\t').append(label);
        }
        return out.toString();
    }
}
