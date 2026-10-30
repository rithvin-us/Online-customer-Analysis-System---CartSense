package com.cartscope.io;

import java.io.IOException;

import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Reducer;

/**
 * Element-wise sum of {@link Aggregate} values for one key.
 *
 * <p>Used as the combiner of every CartScope stage. Because the merge is pure
 * addition (plus a deterministic label collapse), running it zero, one or many
 * times on the map side produces the same result as running it only in the
 * reducer, which is the precondition for using a combiner at all.
 */
public class AggregateSumReducer extends Reducer<Text, Aggregate, Text, Aggregate> {

    private final Aggregate accumulator = new Aggregate();

    @Override
    protected void reduce(Text key, Iterable<Aggregate> values, Context context)
            throws IOException, InterruptedException {
        accumulator.reset(0);
        for (Aggregate value : values) {
            accumulator.merge(value);
        }
        context.write(key, accumulator);
    }
}
