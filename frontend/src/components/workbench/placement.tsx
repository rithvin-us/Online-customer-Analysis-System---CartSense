import { Server } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { formatInteger } from "@/lib/format";
import type { PlacementSummary, TaskAttempt } from "@/lib/types";

/**
 * Where a stage's task attempts actually ran.
 *
 * Each attempt reports the NodeManager that executed it, read from the
 * JobHistoryServer. Several hostnames here is the evidence that the work was
 * distributed across the worker containers rather than run in one place.
 */
export function PlacementPanel({
  summary,
  attempts,
}: {
  summary: PlacementSummary | null;
  attempts: TaskAttempt[] | null;
}) {
  if (!summary || summary.total_attempts === 0) {
    return (
      <p className="px-4 py-6 text-xs text-muted-foreground">
        No task placement was recorded for this stage. The JobHistoryServer reports
        placement once a job is archived; if it was unreachable at the time, the
        placement is left empty rather than filled in.
      </p>
    );
  }

  const maximum = Math.max(
    1,
    ...Object.values(summary.per_host).map((counts) => counts.map + counts.reduce),
  );

  return (
    <div className="space-y-4 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="accent">
          <Server className="size-3" aria-hidden />
          {summary.distinct_hosts} worker{summary.distinct_hosts === 1 ? "" : "s"}
        </Badge>
        <span className="tabular">
          {formatInteger(summary.total_attempts)} task attempts
        </span>
      </div>

      <ul className="space-y-2">
        {summary.hosts.map((host) => {
          const counts = summary.per_host[host] ?? { map: 0, reduce: 0 };
          const total = counts.map + counts.reduce;
          return (
            <li key={host} className="space-y-1">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="truncate font-mono text-2xs">{host}</span>
                <span className="shrink-0 tabular text-muted-foreground">
                  {counts.map} map · {counts.reduce} reduce
                </span>
              </div>
              <div className="flex h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="bg-primary"
                  style={{ width: `${(counts.map / maximum) * 100}%` }}
                  aria-hidden
                />
                <div
                  className="bg-info"
                  style={{ width: `${(counts.reduce / maximum) * 100}%` }}
                  aria-hidden
                />
              </div>
              <span className="sr-only">
                {host} ran {total} attempts: {counts.map} map and {counts.reduce} reduce
              </span>
            </li>
          );
        })}
      </ul>

      {attempts && attempts.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            Every attempt ({formatInteger(attempts.length)})
          </summary>
          <div className="mt-2 max-h-64 overflow-auto scrollbar-slim rounded border border-border">
            <table className="w-full text-2xs">
              <thead className="sticky top-0 bg-surface-sunken">
                <tr className="text-left text-muted-foreground">
                  <th className="px-2 py-1.5 font-medium">Attempt</th>
                  <th className="px-2 py-1.5 font-medium">Type</th>
                  <th className="px-2 py-1.5 font-medium">Worker</th>
                  <th className="px-2 py-1.5 text-right font-medium">Elapsed</th>
                  <th className="px-2 py-1.5 font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {attempts.map((attempt) => (
                  <tr key={attempt.attempt_id} className="border-t border-border/60">
                    <td className="px-2 py-1 font-mono">{attempt.attempt_id}</td>
                    <td className="px-2 py-1">{attempt.type}</td>
                    <td className="px-2 py-1 font-mono">{attempt.host}</td>
                    <td className="px-2 py-1 text-right tabular">
                      {attempt.elapsed_time === null ? "—" : `${attempt.elapsed_time} ms`}
                    </td>
                    <td className="px-2 py-1">{attempt.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
