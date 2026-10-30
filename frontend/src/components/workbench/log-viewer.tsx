"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { ErrorState, LoadingRow } from "./states";

/**
 * Shows a log exactly as the producer wrote it.
 *
 * The content is whatever the API returned — the client-side output of
 * `hadoop jar`, or the aggregated container logs from the NodeManagers. Nothing
 * is synthesised, reformatted or coloured in, because a log that has been
 * prettified is no longer evidence.
 */
export function LogViewer({
  load,
  pollMs = 0,
  emptyMessage = "This log is empty.",
}: {
  load: () => Promise<string>;
  pollMs?: number;
  emptyMessage?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [loading, setLoading] = useState(true);
  const viewport = useRef<HTMLPreElement>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const value = await loadRef.current();
        if (!active) return;
        setText(value);
        setError(null);
      } catch (failure) {
        if (!active) return;
        setError(failure instanceof Error ? failure.message : "the log could not be read");
      } finally {
        if (active) setLoading(false);
      }
    }

    void refresh();
    if (pollMs > 0) {
      const timer = setInterval(() => void refresh(), pollMs);
      return () => {
        active = false;
        clearInterval(timer);
      };
    }
    return () => {
      active = false;
    };
  }, [pollMs]);

  useEffect(() => {
    if (follow && viewport.current) {
      viewport.current.scrollTop = viewport.current.scrollHeight;
    }
  }, [text, follow]);

  async function reload() {
    setLoading(true);
    try {
      setText(await loadRef.current());
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "the log could not be read");
    } finally {
      setLoading(false);
    }
  }

  if (loading && text === null) return <LoadingRow label="Reading the log" />;
  if (error && text === null) return <ErrorState message={error} className="m-4" />;

  const lines = (text ?? "").split("\n").length;

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2">
        <span className="text-2xs tabular text-muted-foreground">{lines} lines</span>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Switch id="follow-log" checked={follow} onCheckedChange={setFollow} />
            <Label htmlFor="follow-log" className="cursor-pointer">
              <ArrowDownToLine className="mr-1 inline size-3" aria-hidden />
              Follow
            </Label>
          </div>
          <Button variant="ghost" size="xs" onClick={() => void reload()} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : undefined} aria-hidden />
            Refresh
          </Button>
        </div>
      </div>
      <pre
        ref={viewport}
        className="min-h-0 flex-1 overflow-auto scrollbar-slim bg-surface-sunken px-4 py-3 font-mono text-2xs leading-relaxed text-foreground/90"
      >
        {text?.trim() ? text : emptyMessage}
      </pre>
    </div>
  );
}
