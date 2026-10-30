import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  Hourglass,
  Loader2,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { RunStatus, VersionStatus } from "@/lib/types";

type Variant = React.ComponentProps<typeof Badge>["variant"];

const RUN: Record<RunStatus, { label: string; variant: Variant; icon: typeof CheckCircle2 }> = {
  PENDING: { label: "Queued", variant: "default", icon: Hourglass },
  RUNNING: { label: "Running", variant: "info", icon: Loader2 },
  SUCCEEDED: { label: "Succeeded", variant: "quiet", icon: CheckCircle2 },
  PARTIAL: { label: "Partial", variant: "warning", icon: AlertTriangle },
  FAILED: { label: "Failed", variant: "danger", icon: XCircle },
  CANCELLED: { label: "Cancelled", variant: "default", icon: CircleSlash },
};

const VERSION: Record<
  VersionStatus,
  { label: string; variant: Variant; icon: typeof CheckCircle2 }
> = {
  RECEIVED: { label: "Received", variant: "default", icon: CircleDashed },
  PROFILING: { label: "Profiling", variant: "info", icon: Loader2 },
  UPLOADING_TO_HDFS: { label: "Writing to HDFS", variant: "info", icon: Loader2 },
  VALIDATING: { label: "Validating", variant: "info", icon: Loader2 },
  READY: { label: "Ready", variant: "quiet", icon: CheckCircle2 },
  FAILED: { label: "Failed", variant: "danger", icon: XCircle },
};

export function StatusPill({
  status,
  kind = "run",
  className,
}: {
  status: RunStatus | VersionStatus;
  kind?: "run" | "version";
  className?: string;
}) {
  const table = kind === "run" ? RUN : VERSION;
  const entry =
    (table as Record<string, { label: string; variant: Variant; icon: typeof CheckCircle2 }>)[
      status
    ] ?? { label: status, variant: "default" as Variant, icon: CircleDashed };
  const Icon = entry.icon;
  const spinning = Icon === Loader2;

  // In the quiet variant the tick is the only coloured thing, so a screen full
  // of healthy rows reads as calm and a failed one is the one row with colour.
  const quiet = entry.variant === "quiet";

  return (
    <Badge variant={entry.variant} className={cn("gap-1", className)}>
      <Icon
        className={cn("size-3", spinning && "animate-spin", quiet && "text-success")}
        aria-hidden
      />
      {entry.label}
    </Badge>
  );
}

/** True while a status still implies work in flight, so polling should continue. */
export function isActive(status: RunStatus | VersionStatus): boolean {
  return (
    status === "PENDING" ||
    status === "RUNNING" ||
    status === "RECEIVED" ||
    status === "PROFILING" ||
    status === "UPLOADING_TO_HDFS" ||
    status === "VALIDATING"
  );
}
