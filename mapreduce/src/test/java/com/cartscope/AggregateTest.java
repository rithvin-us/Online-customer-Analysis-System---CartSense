package com.cartscope;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;

import com.cartscope.io.Aggregate;
import org.junit.jupiter.api.Test;

class AggregateTest {

    @Test
    void addsMetricsElementWise() {
        Aggregate left = Aggregate.of(1.5d, 2.0d, 3.0d);
        left.merge(Aggregate.of(0.5d, 1.0d, 1.0d));
        assertEquals(2.0d, left.get(0));
        assertEquals(3.0d, left.get(1));
        assertEquals(4.0d, left.get(2));
    }

    @Test
    void takesTheMaximumOfMaxSlots() {
        Aggregate left = Aggregate.zeros(1, 1);
        left.setMax(0, 1_000L);
        Aggregate right = Aggregate.zeros(1, 1);
        right.setMax(0, 5_000L);
        left.merge(right);
        assertEquals(5_000L, left.getMaxLong(0));

        // Merging a smaller maximum must not lower the value.
        Aggregate smaller = Aggregate.zeros(1, 1);
        smaller.setMax(0, 10L);
        left.merge(smaller);
        assertEquals(5_000L, left.getMaxLong(0));
    }

    @Test
    void collapsesLabelToSmallestNonEmpty() {
        Aggregate left = Aggregate.labelled("WHITE MUG", 1.0d);
        left.merge(Aggregate.labelled("ALARM CLOCK", 1.0d));
        assertEquals("ALARM CLOCK", left.label());

        Aggregate withEmpty = Aggregate.labelled("", 1.0d);
        withEmpty.merge(Aggregate.labelled("ZEBRA", 1.0d));
        assertEquals("ZEBRA", withEmpty.label());
    }

    @Test
    void mergeIsOrderIndependent() {
        Aggregate forwards = Aggregate.zeros(2);
        forwards.merge(Aggregate.labelled("B", 1.0d, 2.0d));
        forwards.merge(Aggregate.labelled("A", 3.0d, 4.0d));

        Aggregate backwards = Aggregate.zeros(2);
        backwards.merge(Aggregate.labelled("A", 3.0d, 4.0d));
        backwards.merge(Aggregate.labelled("B", 1.0d, 2.0d));

        assertEquals(forwards.toString(), backwards.toString());
    }

    @Test
    void survivesWritableRoundTrip() throws Exception {
        Aggregate original = Aggregate.labelled("RED RETROSPOT", 12.5d, 7.0d);
        original.setMax(0, 1_300_000_000_000L);

        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(bytes)) {
            original.write(out);
        }

        Aggregate restored = new Aggregate();
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
            restored.readFields(in);
        }

        assertEquals(12.5d, restored.get(0));
        assertEquals(7.0d, restored.get(1));
        assertEquals(1_300_000_000_000L, restored.getMaxLong(0));
        assertEquals("RED RETROSPOT", restored.label());
    }

    @Test
    void resetClearsEverything() {
        Aggregate aggregate = Aggregate.labelled("X", 5.0d);
        aggregate.setMax(0, 99L);
        aggregate.reset(2, 1);
        assertEquals(0.0d, aggregate.get(0));
        assertEquals(0.0d, aggregate.get(1));
        assertEquals("", aggregate.label());
        assertEquals(0L, aggregate.getMaxLong(0));
    }
}
