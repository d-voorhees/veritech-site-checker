import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "bg-muted text-foreground",
        high: "bg-red-100 text-red-800",
        medium: "bg-amber-100 text-amber-800",
        low: "bg-blue-100 text-blue-800",
        info: "bg-slate-100 text-slate-700",
        success: "bg-emerald-100 text-emerald-800",
        outline: "border border-border text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function severityToVariant(severity: string): BadgeProps["variant"] {
  switch (severity) {
    case "high":
      return "high";
    case "medium":
      return "medium";
    case "low":
      return "low";
    case "ok":
      return "success";
    default:
      return "info";
  }
}
