package com.cartscope.jobs.support;

import java.io.IOException;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.io.DoubleWritable;
import org.apache.hadoop.io.NullWritable;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;

/**
 * A reusable final MapReduce stage that puts an aggregated result into rank
 * order and numbers the rows.
 *
 * <p>Sorting is the shuffle's job, not the application's: the mapper emits the
 * sort metric as the key, Hadoop sorts the keys, and the reducer walks them in
 * order. For a descending ranking the metric is negated, because Hadoop sorts
 * keys ascending.
 *
 * <p>The stage runs with a single reducer. That is a deliberate choice, not an
 * oversight: a rank is a <em>total</em> order, and with several reducers each
 * one would produce its own independently sorted partition. For a result set
 * of this size (tens of thousands of customers or products at most) one
 * reducer is the correct trade-off; at a scale where it is not, the same stage
 * would be run with {@code TotalOrderPartitioner} and an {@code InputSampler}
 * to build partition boundaries, keeping the output globally ordered across
 * many reducers.
 */
public final class RankStage {

    /** Zero-based index of the tab separated column to sort on. */
    public static final String CONF_COLUMN = "cartscope.rank.column";
    /** Sort direction. */
    public static final String CONF_DESCENDING = "cartscope.rank.descending";
    /** Maximum rows to emit; 0 means every row. */
    public static final String CONF_LIMIT = "cartscope.rank.limit";

    private RankStage() {
    }

    /** Applies the ranking configuration to {@code job}. */
    public static void configure(Job job, int column, boolean descending, int limit) {
        Configuration conf = job.getConfiguration();
        conf.setInt(CONF_COLUMN, column);
        conf.setBoolean(CONF_DESCENDING, descending);
        conf.setInt(CONF_LIMIT, limit);

        job.setMapperClass(RankMapper.class);
        job.setReducerClass(RankReducer.class);
        job.setNumReduceTasks(1);
        job.setMapOutputKeyClass(DoubleWritable.class);
        job.setMapOutputValueClass(Text.class);
        job.setOutputKeyClass(NullWritable.class);
        job.setOutputValueClass(Text.class);
    }

    /** Counters for rows that could not be ranked. */
    public enum Stat {
        RANKED_ROWS,
        UNPARSEABLE_SORT_KEY,
        SHORT_ROWS,
        TRUNCATED_BY_LIMIT
    }

    public static class RankMapper extends Mapper<Object, Text, DoubleWritable, Text> {

        private int column;
        private boolean descending;
        private final DoubleWritable sortKey = new DoubleWritable();

        @Override
        protected void setup(Context context) {
            Configuration conf = context.getConfiguration();
            column = conf.getInt(CONF_COLUMN, 1);
            descending = conf.getBoolean(CONF_DESCENDING, true);
        }

        @Override
        protected void map(Object offset, Text value, Context context)
                throws IOException, InterruptedException {
            String line = value.toString();
            if (line.isEmpty()) {
                return;
            }
            String[] fields = line.split("\t", -1);
            if (column >= fields.length) {
                context.getCounter(Stat.SHORT_ROWS).increment(1L);
                return;
            }
            double metric;
            try {
                metric = Double.parseDouble(fields[column]);
            } catch (NumberFormatException notANumber) {
                context.getCounter(Stat.UNPARSEABLE_SORT_KEY).increment(1L);
                return;
            }
            sortKey.set(descending ? -metric : metric);
            context.write(sortKey, value);
        }
    }

    public static class RankReducer extends Reducer<DoubleWritable, Text, NullWritable, Text> {

        private int limit;
        private long emitted;
        private final Text out = new Text();

        @Override
        protected void setup(Context context) {
            limit = context.getConfiguration().getInt(CONF_LIMIT, 0);
        }

        @Override
        protected void reduce(DoubleWritable sortKey, Iterable<Text> rows, Context context)
                throws IOException, InterruptedException {
            for (Text row : rows) {
                if (limit > 0 && emitted >= limit) {
                    context.getCounter(Stat.TRUNCATED_BY_LIMIT).increment(1L);
                    return;
                }
                emitted++;
                // The rank is prepended so that the ordering survives export,
                // and so that ties are visible as adjacent ranks.
                out.set(emitted + "\t" + row);
                context.write(NullWritable.get(), out);
                context.getCounter(Stat.RANKED_ROWS).increment(1L);
            }
        }
    }
}
