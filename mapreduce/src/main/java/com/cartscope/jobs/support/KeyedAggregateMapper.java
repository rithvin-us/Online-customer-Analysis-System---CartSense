package com.cartscope.jobs.support;

import java.io.IOException;

import com.cartscope.io.Aggregate;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;

/**
 * Reads the tab separated output of a previous stage back into
 * {@code (Text, Aggregate)} pairs so that the next stage can keep summing.
 *
 * <p>Intermediate stages write plain text rather than sequence files. Text
 * costs a little more I/O, and buys the ability to inspect any stage of any
 * pipeline straight from the command line during a demonstration:
 *
 * <pre>
 *   hdfs dfs -cat /cartscope/jobs/&lt;run_id&gt;/customer_analysis/invoice-rollup/part-r-00000
 * </pre>
 *
 * <p>The expected line shape is the one {@link com.cartscope.io.Aggregate}
 * produces: {@code key \t metric0 \t metric1 ... [\t label]}.
 */
public class KeyedAggregateMapper extends Mapper<Object, Text, Text, Aggregate> {

    /** Number of numeric metrics that follow the key. */
    public static final String CONF_WIDTH = "cartscope.tsv.metric.width";
    /** Number of maximum-merged slots that follow the metrics. */
    public static final String CONF_MAX_WIDTH = "cartscope.tsv.max.width";
    /** Whether a trailing text label follows the metrics. */
    public static final String CONF_HAS_LABEL = "cartscope.tsv.has.label";

    public enum Stat {
        MALFORMED_STAGE_ROWS
    }

    private int width;
    private int maxWidth;
    private boolean hasLabel;
    private final Text outKey = new Text();

    /** Declares the shape of the rows this mapper will read. */
    public static void configure(Job job, int metricWidth, boolean hasLabel) {
        configure(job, metricWidth, 0, hasLabel);
    }

    /** Declares the shape of rows that also carry maximum-merged slots. */
    public static void configure(Job job, int metricWidth, int maxWidth, boolean hasLabel) {
        Configuration conf = job.getConfiguration();
        conf.setInt(CONF_WIDTH, metricWidth);
        conf.setInt(CONF_MAX_WIDTH, maxWidth);
        conf.setBoolean(CONF_HAS_LABEL, hasLabel);
        job.setMapperClass(KeyedAggregateMapper.class);
        job.setMapOutputKeyClass(Text.class);
        job.setMapOutputValueClass(Aggregate.class);
    }

    @Override
    protected void setup(Context context) {
        Configuration conf = context.getConfiguration();
        width = conf.getInt(CONF_WIDTH, 1);
        maxWidth = conf.getInt(CONF_MAX_WIDTH, 0);
        hasLabel = conf.getBoolean(CONF_HAS_LABEL, false);
    }

    @Override
    protected void map(Object offset, Text value, Context context)
            throws IOException, InterruptedException {
        String line = value.toString();
        if (line.isEmpty()) {
            return;
        }
        String[] fields = line.split("\t", -1);
        int expected = 1 + width + maxWidth + (hasLabel ? 1 : 0);
        if (fields.length < expected) {
            context.getCounter(Stat.MALFORMED_STAGE_ROWS).increment(1L);
            return;
        }

        Aggregate aggregate = Aggregate.zeros(width, maxWidth);
        try {
            for (int i = 0; i < width; i++) {
                aggregate.set(i, Double.parseDouble(fields[1 + i]));
            }
            for (int i = 0; i < maxWidth; i++) {
                aggregate.setMax(i, Double.parseDouble(fields[1 + width + i]));
            }
        } catch (NumberFormatException notANumber) {
            context.getCounter(Stat.MALFORMED_STAGE_ROWS).increment(1L);
            return;
        }
        if (hasLabel) {
            aggregate.setLabel(fields[1 + width + maxWidth]);
        }

        outKey.set(fields[0]);
        context.write(outKey, aggregate);
    }
}
