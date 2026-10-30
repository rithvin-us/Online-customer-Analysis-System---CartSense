"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Layers, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { generateSynthetic } from "@/lib/api";
import { formatInteger } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const PRESETS = [100_000, 500_000, 1_000_000, 2_000_000] as const;

/**
 * Amplifies a real dataset into a larger one, for benchmarking.
 *
 * What the generator preserves is spelled out here, because a benchmark over
 * data with the wrong shape measures the wrong thing: it resamples whole
 * invoices from the source's own product catalogue, customer population and
 * monthly weighting, and reproduces its rates of missing CustomerID,
 * cancellations and duplicates.
 */
export function SyntheticDialog({
  datasetId,
  sourceVersionId,
  sourceRecords,
  disabled,
  onDone,
}: {
  datasetId: string;
  sourceVersionId: string;
  sourceRecords: number | null;
  disabled?: boolean;
  onDone?: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [targetRows, setTargetRows] = useState<number>(500_000);
  const [seed, setSeed] = useState(20251030);
  const [name, setName] = useState("");

  const submit = useAction(async () =>
    generateSynthetic(datasetId, {
      source_version_id: sourceVersionId,
      target_rows: targetRows,
      seed,
      name: name.trim() || undefined,
    }),
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const created = await submit.run();
    if (!created) return;
    setOpen(false);
    onDone?.();
    router.refresh();
  }

  const multiplier = sourceRecords ? targetRows / sourceRecords : null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm" disabled={disabled}>
          <Layers aria-hidden />
          Generate a larger version
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Generate a larger dataset</DialogTitle>
            <DialogDescription>
              The generated data goes through the same profiling, HDFS upload and Hadoop
              validation as an upload, so a benchmark against it is comparable to one
              against the real data.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label>Target rows</Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setTargetRows(preset)}
                  className={cn(
                    "rounded-md border px-2 py-2 text-xs tabular transition-colors",
                    targetRows === preset
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-surface text-muted-foreground hover:bg-muted",
                  )}
                >
                  {formatInteger(preset)}
                </button>
              ))}
            </div>
            <Input
              type="number"
              min={1000}
              max={20_000_000}
              step={1000}
              value={targetRows}
              onChange={(event) => setTargetRows(Number(event.target.value))}
              className="tabular"
            />
            <p className="text-2xs text-muted-foreground">
              {sourceRecords
                ? `The source has ${formatInteger(sourceRecords)} validated records` +
                  (multiplier ? ` — about ${multiplier.toFixed(1)}x.` : ".")
                : "Rows are emitted a whole invoice at a time, so the final count lands just past the target."}
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="synthetic-seed">Seed</Label>
              <Input
                id="synthetic-seed"
                type="number"
                value={seed}
                onChange={(event) => setSeed(Number(event.target.value))}
                className="tabular"
              />
              <p className="text-2xs text-muted-foreground">
                The same seed reproduces the same dataset.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="synthetic-name">Version label</Label>
              <Input
                id="synthetic-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={`synthetic-${targetRows}-rows.csv`}
                maxLength={200}
              />
            </div>
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
            <Button type="submit" disabled={submit.pending}>
              {submit.pending ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden />
                  Queueing
                </>
              ) : (
                <>
                  <Layers aria-hidden />
                  Generate and validate
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
