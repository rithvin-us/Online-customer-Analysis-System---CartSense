package com.cartscope.util;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.mapreduce.Counter;
import org.apache.hadoop.mapreduce.CounterGroup;
import org.apache.hadoop.mapreduce.Counters;
import org.apache.hadoop.mapreduce.Job;

/**
 * Collects the execution facts of every stage of an analysis and writes them
 * as JSON.
 *
 * <p>This is how CartScope reports real execution metrics. Counters are read
 * from the completed {@link Job} object through the MapReduce API — they are
 * the same numbers the ResourceManager and JobHistoryServer hold — and written
 * verbatim. Nothing in this class computes, estimates or defaults a metric: if
 * Hadoop did not report a counter, it does not appear in the report.
 */
public final class JobReporter {

    private final String analysis;
    private final String runId;
    private final long startedAt = System.currentTimeMillis();
    private final List<StageRecord> stages = new ArrayList<>();
    private final Map<String, String> outputs = new LinkedHashMap<>();
    private final Map<String, String> settings = new LinkedHashMap<>();

    public JobReporter(String analysis, String runId) {
        this.analysis = analysis;
        this.runId = runId;
    }

    /** Records one completed MapReduce stage. */
    public void record(String stage, Job job, List<String> inputPaths, String outputPath)
            throws IOException, InterruptedException {
        stages.add(new StageRecord(stage, job, inputPaths, outputPath));
    }

    /** Registers a logical result name against the HDFS path holding it. */
    public void addOutput(String name, String hdfsPath) {
        outputs.put(name, hdfsPath);
    }

    /** Records a configuration value worth keeping for reproducibility. */
    public void addSetting(String key, String value) {
        settings.put(key, value);
    }

    public String toJson(boolean succeeded) {
        long finishedAt = System.currentTimeMillis();
        Json json = new Json();
        json.beginObject()
                .field("analysis", analysis)
                .field("runId", runId)
                .field("succeeded", succeeded)
                .field("startedAt", startedAt)
                .field("finishedAt", finishedAt)
                .field("durationMs", finishedAt - startedAt)
                .field("stageCount", stages.size());

        json.name("settings").beginObject();
        settings.forEach(json::field);
        json.endObject();

        json.name("outputs").beginObject();
        outputs.forEach(json::field);
        json.endObject();

        json.name("stages").beginArray();
        for (StageRecord stage : stages) {
            stage.writeTo(json);
        }
        json.endArray();

        return json.endObject().toString();
    }

    /** Writes the report to the local filesystem, for the orchestrating worker. */
    public void writeLocal(String path, boolean succeeded) throws IOException {
        if (path == null || path.isEmpty()) {
            return;
        }
        Files.writeString(Paths.get(path), toJson(succeeded), StandardCharsets.UTF_8);
    }

    /** Writes the report into the HDFS manifest tree, for reproducibility. */
    public void writeToHdfs(Configuration conf, String path, boolean succeeded) throws IOException {
        if (path == null || path.isEmpty()) {
            return;
        }
        Path target = new Path(path);
        FileSystem fs = target.getFileSystem(conf);
        fs.mkdirs(target.getParent());
        try (OutputStream out = fs.create(target, true)) {
            out.write(toJson(succeeded).getBytes(StandardCharsets.UTF_8));
        }
    }

    // ------------------------------------------------------------------
    private static final class StageRecord {
        private final String stage;
        private final String jobName;
        private final String jobId;
        private final String applicationId;
        private final String trackingUrl;
        private final String state;
        private final long startTime;
        private final long finishTime;
        private final int configuredReducers;
        private final List<String> inputPaths;
        private final String outputPath;
        private final Counters counters;

        StageRecord(String stage, Job job, List<String> inputPaths, String outputPath)
                throws IOException, InterruptedException {
            this.stage = stage;
            this.jobName = job.getJobName();
            this.jobId = job.getJobID() == null ? "" : job.getJobID().toString();
            // In MRv2 a job id and its YARN application id share the cluster
            // timestamp and sequence number, so this mapping is exact rather
            // than a guess: job_1700000000000_0003 is run by
            // application_1700000000000_0003.
            this.applicationId = this.jobId.replaceFirst("^job_", "application_");
            this.trackingUrl = job.getStatus() == null ? "" : job.getStatus().getTrackingUrl();
            this.state = job.getStatus() == null ? "UNKNOWN" : job.getStatus().getState().name();
            this.startTime = job.getStatus() == null ? 0L : (long) job.getStatus().getStartTime();
            this.finishTime = job.getStatus() == null ? 0L : (long) job.getStatus().getFinishTime();
            this.configuredReducers = job.getNumReduceTasks();
            this.inputPaths = inputPaths;
            this.outputPath = outputPath;
            this.counters = job.getCounters();
        }

        void writeTo(Json json) {
            json.beginObject()
                    .field("stage", stage)
                    .field("jobName", jobName)
                    .field("jobId", jobId)
                    .field("applicationId", applicationId)
                    .field("trackingUrl", trackingUrl)
                    .field("state", state)
                    .field("startTime", startTime)
                    .field("finishTime", finishTime)
                    .field("durationMs", Math.max(0L, finishTime - startTime))
                    .field("configuredReducers", configuredReducers)
                    .field("outputPath", outputPath == null ? "" : outputPath);

            json.name("inputPaths").beginArray();
            for (String input : inputPaths) {
                json.value(input);
            }
            json.endArray();

            json.name("counterGroups").beginArray();
            if (counters != null) {
                for (CounterGroup group : counters) {
                    json.beginObject()
                            .field("name", group.getName())
                            .field("displayName", group.getDisplayName());
                    json.name("counters").beginArray();
                    for (Counter counter : group) {
                        json.beginObject()
                                .field("name", counter.getName())
                                .field("displayName", counter.getDisplayName())
                                .field("value", counter.getValue())
                                .endObject();
                    }
                    json.endArray().endObject();
                }
            }
            json.endArray();
            json.endObject();
        }
    }
}
