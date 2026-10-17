import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "border-border bg-muted text-muted-foreground",
        healthy: "border-success/25 bg-success/10 text-success",
        attention: "border-warning/25 bg-warning/10 text-warning",
        blocked: "border-destructive/25 bg-destructive/10 text-destructive",
        accent: "border-primary/25 bg-primary/10 text-primary-foreground",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ className, variant }))} {...props} />
  );
}
