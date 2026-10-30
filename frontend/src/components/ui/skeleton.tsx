import { cn } from "@/lib/utils";

/**
 * A loading placeholder. It does not pulse: a console that blinks while it
 * waits is harder to read than one that simply shows a flat block.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded bg-muted/70", className)} {...props} />;
}

export { Skeleton };
