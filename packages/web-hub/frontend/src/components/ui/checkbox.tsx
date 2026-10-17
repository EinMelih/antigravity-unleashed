import { Check } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const Checkbox = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, ...props }, ref) => (
    <span className={cn("relative inline-flex size-4 shrink-0", className)}>
      <input
        className="peer absolute inset-0 z-10 size-4 cursor-pointer appearance-none rounded border border-input bg-background outline-none transition-colors checked:border-primary checked:bg-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        ref={ref}
        type="checkbox"
        {...props}
      />
      <Check className="pointer-events-none absolute inset-0.5 hidden size-3 text-primary-foreground peer-checked:block" strokeWidth={3} />
    </span>
  ),
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
