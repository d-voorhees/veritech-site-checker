"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreVertical, Plus, Trash2 } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ScanStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ScanSummary } from "@/lib/api";
import { productConfig } from "@/lib/config";
import { useRequireAuth } from "@/lib/use-auth";
import { formatDateTime } from "@/lib/utils";

const ACTIVE_STATUSES = new Set(["queued", "starting", "running"]);

const CHECK_CATEGORIES = [
  "Site behavior and redirects",
  "Email and domain posture",
  "Crawl and structure",
  "Technology stack",
  "Third-party dependencies",
  "Performance",
];

export default function DashboardPage() {
  useRequireAuth();
  const { data: scans, isLoading } = useQuery({ queryKey: ["scans", "mine"], queryFn: api.listScans });
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const recent = (scans ?? []).slice(0, 8);
  const inProgress = (scans ?? []).filter((s) => s.status === "queued" || s.status === "running");
  const hasNeverScanned = !isLoading && (scans?.length ?? 0) === 0;

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <div>
          <div className="eyebrow text-primary">Overview</div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-foreground">Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {productConfig.productName} pre-screens are bounded, evidence-linked, and never conclusive on their
            own — use them to prioritize deeper diligence.
          </p>
        </div>
        {!hasNeverScanned && (
          <Link href="/scans/new">
            <Button>
              <Plus className="h-4 w-4" />
              New scan
            </Button>
          </Link>
        )}
      </div>

      {hasNeverScanned ? (
        <Card className="mt-8">
          <CardContent className="flex flex-col items-center gap-6 px-6 py-14 text-center">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-foreground">Run your first scan</h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                Enter a domain you own or are authorized to evaluate. In a few minutes you&rsquo;ll get a{" "}
                {productConfig.reportName.toLowerCase()} with evidence-linked findings across six categories.
              </p>
            </div>

            <Link href="/scans/new">
              <Button size="lg">
                <Plus className="h-4 w-4" />
                Start your first scan
              </Button>
            </Link>

            <div className="mt-2 grid w-full max-w-md grid-cols-2 gap-x-6 gap-y-2 text-left text-sm text-muted-foreground">
              {CHECK_CATEGORIES.map((category) => (
                <div key={category} className="flex items-center gap-2">
                  <span className="h-1 w-1 shrink-0 rounded-full bg-primary" />
                  {category}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="mt-8 grid grid-cols-1 divide-y divide-border border border-border bg-surface shadow-sm sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <div className="flex flex-col gap-1 px-5 py-4">
              <span className="eyebrow mb-0 text-muted-foreground">Total scans</span>
              <span className="font-mono text-3xl font-bold text-foreground">{scans?.length ?? "—"}</span>
            </div>
            <div className="flex flex-col gap-1 px-5 py-4">
              <span className="eyebrow mb-0 text-muted-foreground">In progress</span>
              <span className="font-mono text-3xl font-bold text-foreground">{inProgress.length}</span>
            </div>
            <div className="flex flex-col gap-1 px-5 py-4">
              <span className="eyebrow mb-0 text-muted-foreground">Product</span>
              <span className="font-mono text-lg font-bold text-foreground">{productConfig.productName}</span>
            </div>
          </div>

          <Card className="mt-8">
            <CardHeader>
              <CardTitle>Recent scans</CardTitle>
              <CardDescription>Your most recently created scans.</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {isLoading && <p className="px-5 py-4 text-sm text-muted-foreground">Loading…</p>}
              <ul className="divide-y divide-border">
                {recent.map((scan) => (
                  <li
                    key={scan.id}
                    className={`group relative flex items-center justify-between px-5 py-3 text-sm hover:bg-muted ${
                      openMenuId === scan.id ? "z-20" : ""
                    }`}
                  >
                    <Link
                      href={`/scans/${scan.id}`}
                      className="absolute inset-0 z-0"
                      aria-label={`View scan for ${scan.normalized_domain}`}
                    />
                    <div className="pointer-events-none">
                      <div className="font-medium">
                        {scan.normalized_domain}
                        {scan.is_demo && <span className="ml-2 text-xs text-muted-foreground">(demo)</span>}
                      </div>
                      <div className="text-xs text-muted-foreground">{formatDateTime(scan.created_at)}</div>
                    </div>
                    <div className="relative z-10 flex items-center gap-2">
                      <ScanStatusBadge status={scan.status} />
                      {!ACTIVE_STATUSES.has(scan.status) && (
                        <ScanRowMenu
                          scan={scan}
                          open={openMenuId === scan.id}
                          onOpenChange={(v) => setOpenMenuId(v ? scan.id : null)}
                        />
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </AppShell>
  );
}

function ScanRowMenu({
  scan,
  open,
  onOpenChange,
}: {
  scan: ScanSummary;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteScan(scan.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scans", "mine"] });
    },
  });

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) onOpenChange(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open, onOpenChange]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        title="Scan options"
        aria-label="Scan options"
        className="flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-border hover:text-foreground"
        onClick={() => onOpenChange(!open)}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-40 rounded-md border border-border bg-surface py-1 shadow-md">
          <button
            type="button"
            disabled={deleteMutation.isPending}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-red-600 hover:bg-muted disabled:opacity-50"
            onClick={() => {
              if (window.confirm(`Delete the scan for ${scan.normalized_domain}? This cannot be undone.`)) {
                deleteMutation.mutate();
              }
              onOpenChange(false);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {deleteMutation.isPending ? "Deleting…" : "Delete scan"}
          </button>
        </div>
      )}
    </div>
  );
}
