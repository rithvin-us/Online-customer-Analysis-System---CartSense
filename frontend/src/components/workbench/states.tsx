import { AlertCircle, Inbox, Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center",
        className,
      )}
    >
      <Inbox className="size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="max-w-md text-xs text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "That request failed",
  message,
  className,
}: {
  title?: string;
  message: string;
  className?: string;
}) {
  return (
    <Alert variant="danger" className={className}>
      <AlertCircle aria-hidden />
      <div className="min-w-0">
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription className="mt-0.5 break-words font-mono text-2xs">
          {message}
        </AlertDescription>
      </div>
    </Alert>
  );
}

export function LoadingRow({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" aria-hidden />
      {label}
    </div>
  );
}
