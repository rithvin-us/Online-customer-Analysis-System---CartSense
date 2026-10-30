package com.cartscope;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;

import com.cartscope.jobs.CountrySalesJob;
import com.cartscope.jobs.CustomerSpendingJob;
import com.cartscope.jobs.MonthlySalesJob;
import com.cartscope.jobs.ProductPopularityJob;
import com.cartscope.jobs.RepeatCustomerJob;
import com.cartscope.jobs.RfmAnalysisJob;
import com.cartscope.jobs.ValidationJob;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.util.Tool;
import org.apache.hadoop.util.ToolRunner;

/**
 * Entry point of the CartScope job jar.
 *
 * <pre>
 *   hadoop jar cartscope-mapreduce.jar &lt;analysis&gt; [-D key=value ...] \
 *       --input  &lt;hdfs path&gt;      (repeatable)
 *       --work   &lt;hdfs dir&gt;       intermediate stage output
 *       --output &lt;hdfs dir&gt;       final results
 *       --run-id &lt;id&gt;
 *       --report &lt;local file&gt;     counters and job ids, as JSON
 *       --manifest &lt;hdfs file&gt;    the same JSON, kept with the data
 * </pre>
 *
 * <p>{@code ToolRunner} is used rather than a bare {@code main} so that the
 * standard Hadoop options — {@code -D}, {@code -conf}, {@code -files},
 * {@code -libjars} — work on every analysis without the drivers knowing about
 * them. That is how the backend overrides the reducer count or the split size
 * of an individual run.
 */
public final class CartScopeDriver {

    private static final Map<String, Supplier<Tool>> ANALYSES = new LinkedHashMap<>();

    static {
        ANALYSES.put("validate", ValidationJob::new);
        ANALYSES.put("customer_analysis", CustomerSpendingJob::new);
        ANALYSES.put("monthly_sales", MonthlySalesJob::new);
        ANALYSES.put("product_analysis", ProductPopularityJob::new);
        ANALYSES.put("country_analysis", CountrySalesJob::new);
        ANALYSES.put("repeat_customers", RepeatCustomerJob::new);
        ANALYSES.put("rfm_analysis", RfmAnalysisJob::new);
    }

    private CartScopeDriver() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
            System.exit(64);
        }
        String analysis = args[0];
        Supplier<Tool> factory = ANALYSES.get(analysis);
        if (factory == null) {
            System.err.println("unknown analysis: " + analysis);
            usage();
            System.exit(64);
        }

        String[] remaining = new String[args.length - 1];
        System.arraycopy(args, 1, remaining, 0, remaining.length);

        int status = ToolRunner.run(new Configuration(), factory.get(), remaining);
        System.exit(status);
    }

    private static void usage() {
        System.err.println("usage: hadoop jar cartscope-mapreduce.jar <analysis> [options]");
        System.err.println("analyses:");
        for (String name : ANALYSES.keySet()) {
            System.err.println("  " + name);
        }
    }
}
