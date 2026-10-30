"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorState } from "./states";
import { getAnalyses, submitRun } from "@/lib/api";
import { formatBytes, formatInteger } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import type { AnalysisDefinition } from "@/lib/types";

const SPLIT_PRESETS = [
  { label: "Block size", value: null },
  { label: "2 MiB", value: 2_097_152 },
  { label: "1 MiB", value: 1_048_576 },
  { label: "512 KiB", value: 524_288 },
] as const;

/**
 * Chooses analyses and the Hadoop settings to run them under.
 *
 * The two settings offered are the ones that visibly change how the work is
 * distributed: the reducer count, and a split size ceiling that creates more
 * map tasks over the same data. Both are passed to Hadoop as -D options, and
 * both are recorded with the run so a benchmark can say what differed.
 */
export function SubmitRun({
  datasetVersionId,
  versionLabel,
  validatedRecords,
  disabled,
  trigger,
}: {
  datasetVersionId: string;
  versionLabel?: string;
  validatedRecords?: number | null;
  disabled?: boolean;
  trigger?: React.ReactNode;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const analyses = useResource(getAnalyses, { enabled: open });
  const [selected, setSelected] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [reducers, setReducers] = useState(3);
  const [splitMaxsize, setSplitMaxsize] = useState<number | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    if (analyses.data && selected.length === 0) {
      // Default to the five core analyses; RFM is marked optional.
      setSelected(
        analyses.data.filter((analysis) => !analysis.optional).map((analysis) => analysis.key),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyses.data]);

  const submit = useAction(async () =>
    submitRun({
      dataset_version_id: datasetVersionId,
      analyses: selected,
      label: label.trim() || null,
      configuration: {
        reducers,
        split_maxsize: splitMaxsize,
      },
    }),
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const run = await submit.run();
    if (!run) return;
    setOpen(false);
    router.push(`/runs/${run.id}`);
  }

  function toggle(key: string) {
    setSelected((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  const totalStages = (analyses.data ?? [])
    .filter((analysis) => selected.includes(analysis.key))
    .reduce((sum, analysis) => sum + analysis.stage_count, 0);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm" disabled={disabled}>
            <Play aria-hidden />
            Run analyses
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto scrollbar-slim">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Submit a run</DialogTitle>
            <DialogDescription>
              {versionLabel ? `Against ${versionLabel}. ` : ""}
              {validatedRecords
                ? `${formatInteger(validatedRecords)} validated records. `
                : ""}
              Each analysis is a chain of real MapReduce jobs; they run one after another
              so their timings are comparable.
            </DialogDescription>
          </DialogHeader>

          {analyses.loading ? (
            <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              Reading the analysis catalogue
            </div>
          ) : analyses.error ? (
            <ErrorState message={analyses.error} />
          ) : (
            <div className="space-y-2">
              {analyses.data?.map((analysis: AnalysisDefinition) => {
                const checked = selected.includes(analysis.key);
                return (
                  <label
                    key={analysis.key}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors",
                      checked
                        ? "border-primary/50 bg-primary/5"
                        : "border-border bg-surface hover:bg-muted/50",
                    )}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggle(analysis.key)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-medium">{analysis.title}</span>
                        <span className="text-2xs text-muted-foreground">
                          {analysis.stage_count} MapReduce job
                          {analysis.stage_count === 1 ? "" : "s"}
                        </span>
                        {analysis.optional && (
                          <span className="rounded border border-border px-1 text-2xs text-muted-foreground">
                            optional
                          </span>
                        )}
                      </span>
                      <span className="block pt-0.5 text-2xs text-muted-foreground">
                        {analysis.objective}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="run-label">Label</Label>
            <Input
              id="run-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="baseline, 3 reducers"
              maxLength={200}
            />
            <p className="text-2xs text-muted-foreground">
              Labels make a benchmark table readable later.
            </p>
          </div>

          <div className="rounded-md border border-border">
            <button
              type="button"
              onClick={() => setShowAdvanced((current) => !current)}
              className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground"
            >
              <Settings2 className="size-3.5" aria-hidden />
              Hadoop settings
              <span className="ml-auto tabular text-2xs">
                {reducers} reducers ·{" "}
                {splitMaxsize ? formatBytes(splitMaxsize) : "block-sized splits"}
              </span>
            </button>
            {showAdvanced && (
              <div className="space-y-4 border-t border-border px-3 py-3">
                <div className="space-y-1.5">
                  <Label htmlFor="run-reducers">Reducers per stage</Label>
                  <Input
                    id="run-reducers"
                    type="number"
                    min={1}
                    max={32}
                    value={reducers}
                    onChange={(event) => setReducers(Number(event.target.value))}
                    className="tabular"
                  />
                  <p className="text-2xs text-muted-foreground">
                    Passed as <span className="font-mono">-D cartscope.reducers</span>.
                    Ranking and summary stages override this with a single reducer, because
                    a total order and a population summary are each one group.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label>Maximum split size</Label>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {SPLIT_PRESETS.map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        onClick={() => setSplitMaxsize(preset.value)}
                        className={cn(
                          "rounded-md border px-2 py-1.5 text-2xs transition-colors",
                          splitMaxsize === preset.value
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border bg-surface text-muted-foreground hover:bg-muted",
                        )}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-2xs text-muted-foreground">
                    Lowering this creates more map tasks over the same data, which is how
                    to see the work spread further across the three NodeManagers.
                  </p>
                </div>
              </div>
            )}
          </div>

          {submit.error && <ErrorState message={submit.error} />}

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={submit.pending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submit.pending || selected.length === 0}>
              {submit.pending ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden />
                  Submitting
                </>
              ) : (
                <>
                  <Play aria-hidden />
                  Submit {selected.length} analys{selected.length === 1 ? "is" : "es"}
                  {totalStages > 0 && ` · ${totalStages} jobs`}
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
