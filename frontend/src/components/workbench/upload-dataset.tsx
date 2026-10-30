"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Upload } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import { ErrorState } from "./states";
import { uploadDataset, uploadVersion } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { formatBytes } from "@/lib/format";

const EXPECTED_COLUMNS = [
  "InvoiceNo",
  "StockCode",
  "Description",
  "Quantity",
  "InvoiceDate",
  "UnitPrice",
  "CustomerID",
  "Country",
];

/**
 * Upload form for a new dataset, or for a new version of an existing one.
 *
 * The expected schema is stated up front rather than discovered after a failed
 * upload, and the date interpretation is asked for rather than guessed, because
 * 3/4/2011 is genuinely ambiguous and the answer changes every monthly figure.
 */
export function UploadDataset({
  datasetId,
  maxUploadMb,
  trigger,
  onDone,
}: {
  datasetId?: string;
  maxUploadMb?: number;
  trigger?: React.ReactNode;
  onDone?: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [dayFirst, setDayFirst] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = useAction(async () => {
    if (!file) throw new Error("choose a CSV file first");
    const form = new FormData();
    form.set("file", file);
    form.set("day_first", String(dayFirst));
    if (datasetId) {
      return await uploadVersion(datasetId, form);
    }
    form.set("name", name.trim() || file.name.replace(/\.[^.]+$/, ""));
    if (description.trim()) form.set("description", description.trim());
    return await uploadDataset(form);
  });

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const result = await submit.run();
    if (!result) return;
    setOpen(false);
    setFile(null);
    setName("");
    setDescription("");
    if (inputRef.current) inputRef.current.value = "";
    onDone?.();
    if (!datasetId && "id" in result) {
      router.push(`/datasets/${result.id}`);
    } else {
      router.refresh();
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm">
            <Upload aria-hidden />
            {datasetId ? "Add a version" : "Load a dataset"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>
              {datasetId ? "Add a dataset version" : "Load a retail dataset"}
            </DialogTitle>
            <DialogDescription>
              The file is profiled, stored in HDFS unmodified, and then validated by a
              Hadoop MapReduce job. Only a validated version can be analysed.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-1.5">
            <Label htmlFor="dataset-file">CSV file</Label>
            <Input
              id="dataset-file"
              ref={inputRef}
              type="file"
              accept=".csv,.txt,.tsv,text/csv"
              required
              onChange={(event) => {
                const chosen = event.target.files?.[0] ?? null;
                setFile(chosen);
                if (chosen && !name) setName(chosen.name.replace(/\.[^.]+$/, ""));
              }}
            />
            <p className="text-2xs text-muted-foreground">
              Expected columns:{" "}
              <span className="font-mono">{EXPECTED_COLUMNS.join(", ")}</span>
              {maxUploadMb ? ` · up to ${maxUploadMb} MB` : ""}
              {file ? ` · selected ${formatBytes(file.size)}` : ""}
            </p>
          </div>

          {!datasetId && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="dataset-name">Name</Label>
                <Input
                  id="dataset-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="UCI Online Retail"
                  maxLength={200}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dataset-description">Description</Label>
                <Textarea
                  id="dataset-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Where this data came from and what it covers."
                />
              </div>
            </>
          )}

          <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
            <Checkbox
              checked={dayFirst}
              onCheckedChange={(checked) => setDayFirst(checked === true)}
              className="mt-0.5"
            />
            <span className="text-xs">
              <span className="font-medium">Dates are day/month</span>
              <span className="block text-2xs text-muted-foreground">
                Leave this off for the UCI Online Retail exports, which are month/day.
                It decides how 3/4/2011 is read, and that changes every monthly figure.
              </span>
            </span>
          </label>

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
            <Button type="submit" disabled={submit.pending || !file}>
              {submit.pending ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden />
                  Uploading
                </>
              ) : (
                <>
                  <Upload aria-hidden />
                  Upload and validate
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
