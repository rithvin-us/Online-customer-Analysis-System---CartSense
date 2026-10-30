package com.cartscope.jobs;

import java.io.IOException;
import java.util.List;

import com.cartscope.util.CliArgs;
import com.cartscope.util.JobReporter;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.conf.Configured;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.lib.input.FileInputFormat;
import org.apache.hadoop.mapreduce.lib.output.FileOutputFormat;
import org.apache.hadoop.util.Tool;

/**
 * Shared scaffolding for the CartScope analyses.
 *
 * <p>Every analysis is a chain of one or more real MapReduce jobs. This class
 * owns the parts that are identical across them: argument handling, the work
 * and result directory conventions, reducer counts, and the job report that
 * carries the real counters back to the backend.
 *
 * <p>Two directory rules are enforced here and they matter for the product:
 *
 * <ul>
 *   <li>the <em>work</em> directory (under {@code /cartscope/jobs/<run_id>})
 *       holds intermediate stage output and is cleared before a run, because
 *       it is scratch space;</li>
 *   <li>the <em>results</em> directory (under
 *       {@code /cartscope/results/<run_id>}) must not already exist. A
 *       successful analytical output is never overwritten; a repeat of the
 *       same analysis gets a new run id.</li>
 * </ul>
 */
public abstract class AbstractAnalysis extends Configured implements Tool {

    /** Default number of reducers, overridable per stage. */
    public static final String CONF_REDUCERS = "cartscope.reducers";

    protected List<String> inputPaths;
    protected Path workDir;
    protected Path resultDir;
    protected String runId;
    protected JobReporter reporter;

    /** Short name used in job names, report files and HDFS paths. */
    protected abstract String analysisName();

    /** Runs the stages. Returns true when every stage succeeded. */
    protected abstract boolean execute() throws Exception;

    @Override
    public final int run(String[] args) throws Exception {
        CliArgs parsed = CliArgs.parse(args);
        inputPaths = parsed.inputs();
        workDir = new Path(parsed.require("work"));
        resultDir = new Path(parsed.require("output"));
        runId = parsed.optional("run-id", "adhoc");
        String reportPath = parsed.optional("report", "");
        String manifestPath = parsed.optional("manifest", "");

        reporter = new JobReporter(analysisName(), runId);
        reporter.addSetting("hadoop.version", org.apache.hadoop.util.VersionInfo.getVersion());
        reporter.addSetting("dfs.blocksize", getConf().get("dfs.blocksize", "unset"));
        reporter.addSetting("dfs.replication", getConf().get("dfs.replication", "unset"));
        reporter.addSetting("mapreduce.job.reduces.default", String.valueOf(defaultReducers()));
        reporter.addSetting("mapreduce.input.fileinputformat.split.maxsize",
                getConf().get("mapreduce.input.fileinputformat.split.maxsize", "unset"));

        prepareDirectories();

        boolean succeeded = false;
        try {
            succeeded = execute();
        } finally {
            reporter.writeLocal(reportPath, succeeded);
            try {
                reporter.writeToHdfs(getConf(), manifestPath, succeeded);
            } catch (IOException manifestFailure) {
                // A missing manifest must not mask the outcome of the analysis.
                System.err.println("[cartscope] failed to write manifest: " + manifestFailure.getMessage());
            }
        }
        return succeeded ? 0 : 1;
    }

    private void prepareDirectories() throws IOException {
        FileSystem fs = workDir.getFileSystem(getConf());
        if (fs.exists(workDir)) {
            fs.delete(workDir, true);
        }
        fs.mkdirs(workDir);

        checkResultDir(resultDir.getFileSystem(getConf()));
    }

    /**
     * Refuses to start when the analysis would overwrite an existing result.
     * Overridden by the validation job, whose target directory is a dataset
     * version directory that legitimately already holds the raw upload.
     */
    protected void checkResultDir(FileSystem fs) throws IOException {
        if (fs.exists(resultDir)) {
            throw new IOException("result directory already exists and will not be overwritten: "
                    + resultDir + " -- start a new run instead");
        }
    }

    protected int defaultReducers() {
        return getConf().getInt(CONF_REDUCERS, 3);
    }

    /**
     * Reducer count for a stage. A stage-specific override wins, for example
     * {@code -Dcartscope.reducers.rank=1}.
     */
    protected int reducersFor(String stage, int fallback) {
        return getConf().getInt(CONF_REDUCERS + "." + stage, fallback);
    }

    /** Creates a job with the CartScope naming convention. */
    protected Job newJob(String stage) throws IOException {
        Job job = Job.getInstance(getConf(),
                String.format("cartscope:%s:%s:%s", analysisName(), stage, runId));
        job.setJarByClass(getClass());
        return job;
    }

    protected Path stagePath(String stage) {
        return new Path(workDir, stage);
    }

    protected void addInputs(Job job, List<String> paths) throws IOException {
        for (String path : paths) {
            FileInputFormat.addInputPath(job, new Path(path));
        }
    }

    protected void addInput(Job job, Path path) throws IOException {
        FileInputFormat.addInputPath(job, path);
    }

    protected void setOutput(Job job, Path path) {
        FileOutputFormat.setOutputPath(job, path);
    }

    /**
     * Submits a stage, waits for it, and records its real counters.
     *
     * @return true when the stage succeeded
     */
    protected boolean runStage(String stage, Job job, List<String> inputs, Path output)
            throws Exception {
        System.out.printf("[cartscope] submitting stage '%s' of analysis '%s'%n", stage, analysisName());
        boolean ok = job.waitForCompletion(true);
        reporter.record(stage, job, inputs, output == null ? "" : output.toString());
        System.out.printf("[cartscope] stage '%s' finished: jobId=%s state=%s%n",
                stage, job.getJobID(), job.getStatus().getState());
        return ok;
    }

    /**
     * Applies a split size ceiling when one is configured, so that a small
     * demonstration dataset can still be processed by several map tasks across
     * the worker containers.
     */
    protected void applySplitSizeHint(Configuration conf) {
        long maxSplit = conf.getLong("cartscope.split.maxsize", 0L);
        if (maxSplit > 0L) {
            conf.setLong("mapreduce.input.fileinputformat.split.maxsize", maxSplit);
        }
    }
}
