import * as React from "react";
import { type VariantProps, cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative flex gap-3 rounded-md border px-3.5 py-3 text-xs [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:translate-y-0.5",
  {
    variants: {
      variant: {
        default: "border-border bg-surface text-foreground",
        info: "border-info/30 bg-info/5 text-foreground [&>svg]:text-info",
        warning: "border-warning/30 bg-warning/5 text-foreground [&>svg]:text-warning",
        danger:
          "border-destructive/30 bg-destructive/5 text-foreground [&>svg]:text-destructive",
        success: "border-success/30 bg-success/5 text-foreground [&>svg]:text-success",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Alert({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}

function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("font-semibold leading-tight", className)} {...props} />;
}

function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-muted-foreground", className)} {...props} />;
}

export { Alert, AlertDescription, AlertTitle };
