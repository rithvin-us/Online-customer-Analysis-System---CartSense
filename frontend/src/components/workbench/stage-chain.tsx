import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDuration } from "@/lib/format";
import type { JobExecution } from "@/lib/types";

/**
 * The chain of MapReduce jobs an analysis ran, in order.
 *
 * An analysis is not one job: it is a sequence, and the sequence is the point.
 * Showing it as a chain makes it legible why, for instance, a customer figure
 * takes three jobs to compute.
 */
export function StageChain({
  jobs,
  selected,
  onSelect,
  className,
}: {
  jobs: JobExecution[];
  selected?: string;
  onSelect?: (stage: string) => void;
  className?: string;
}) {
  if (jobs.length === 0) {
    return (
      <p className={cn("text-xs text-muted-foreground", className)}>
        No stage has been submitted yet.
      </p>
    );
  }

  return (
    <ol className={cn("flex flex-wrap items-stretch gap-1", className)}>
      {jobs.map((job, index) => {
        const active = selected === job.stage;
        const failed = (job.failed_map_tasks ?? 0) + (job.failed_reduce_tasks ?? 0) > 0;
        return (
          <li key={job.stage} className="flex items-stretch gap-1">
            <button
              type="button"
              onClick={onSelect ? () => onSelect(job.stage) : undefined}
              disabled={!onSelect}
              className={cn(
                "flex min-w-[9.5rem] flex-col items-start gap-0.5 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                active
                  ? "border-primary bg-primary/5"
                  : "border-border bg-surface hover:bg-muted/60",
                !onSelect && "cursor-default",
              )}
              aria-current={active ? "step" : undefined}
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="truncate text-xs font-medium">{job.stage}</span>
                <span className="shrink-0 text-2xs tabular text-muted-foreground">
                  {index + 1}/{jobs.length}
                </span>
              </span>
              <span className="flex w-full items-center justify-between gap-2 text-2xs text-muted-foreground">
                <span className="tabular">{formatDuration(job.duration_ms)}</span>
                <span className="tabular">
                  {job.launched_map_tasks ?? "—"}m / {job.launched_reduce_tasks ?? "—"}r
                </span>
              </span>
              {failed && (
                <span className="text-2xs text-destructive">
                  {(job.failed_map_tasks ?? 0) + (job.failed_reduce_tasks ?? 0)} task failures
                </span>
              )}
            </button>
            {index < jobs.length - 1 && (
              <ArrowRight
                className="size-3.5 self-center text-muted-foreground/60"
                aria-hidden
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
