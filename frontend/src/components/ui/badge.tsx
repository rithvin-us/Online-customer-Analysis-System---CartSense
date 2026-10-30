import * as React from "react";
import { type VariantProps, cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-medium",
  {
    variants: {
      variant: {
        default: "border-border bg-muted text-muted-foreground",
        outline: "border-border text-foreground",
        // For a state that is simply normal. The icon beside it carries the
        // meaning; a filled green pill on every healthy row means nothing
        // leads, and the one failing row stops standing out.
        quiet: "border-border/70 bg-transparent text-muted-foreground",
        success: "border-success/30 bg-success/10 text-success",
        warning: "border-warning/30 bg-warning/10 text-warning",
        danger: "border-destructive/30 bg-destructive/10 text-destructive",
        info: "border-info/30 bg-info/10 text-info",
        accent: "border-primary/30 bg-primary/10 text-primary",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
