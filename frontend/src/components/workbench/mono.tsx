"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A machine identifier: a job id, an application id, an HDFS path, a checksum.
 *
 * These are the values an operator copies into a terminal, so they are set in
 * monospace, never truncated silently without the full value on hover, and
 * copyable in one click.
 */
export function Mono({
  value,
  truncate,
  className,
  copyable = true,
  title,
}: {
  value: string | null | undefined;
  truncate?: number;
  className?: string;
  copyable?: boolean;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);

  if (!value) {
    return <span className="text-muted-foreground">—</span>;
  }

  const shown =
    truncate && value.length > truncate ? `${value.slice(0, truncate - 1)}…` : value;

  async function copy() {
    try {
      await navigator.clipboard.writeText(value!);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard access can be refused; the full value is in the title
      // attribute either way, so there is nothing to recover from.
    }
  }

  return (
    <span className={cn("group/mono inline-flex max-w-full items-center gap-1", className)}>
      <code
        className="truncate font-mono text-2xs text-foreground/90"
        title={title ?? value}
      >
        {shown}
      </code>
      {copyable && (
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Copied" : `Copy ${value}`}
          className="shrink-0 text-muted-foreground opacity-0 transition-opacity focus-visible:opacity-100 group-hover/mono:opacity-100"
        >
          {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
        </button>
      )}
    </span>
  );
}
