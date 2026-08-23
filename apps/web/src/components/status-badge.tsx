import { Badge } from "@/components/ui/badge";

const STATUS_STYLES: Record<string, { label: string; variant: "success" | "medium" | "high" | "info" | "default" }> = {
  queued: { label: "Queued", variant: "info" },
  starting: { label: "Starting", variant: "info" },
  running: { label: "Running", variant: "medium" },
  completed: { label: "Completed", variant: "success" },
  completed_with_warnings: { label: "Completed with warnings", variant: "medium" },
  failed: { label: "Failed", variant: "high" },
  cancelled: { label: "Cancelled", variant: "default" },
};

export function ScanStatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? { label: status, variant: "default" as const };
  return <Badge variant={style.variant}>{style.label}</Badge>;
}
