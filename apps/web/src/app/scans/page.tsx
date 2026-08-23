"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ScanStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { formatDateTime } from "@/lib/utils";

export default function ScansListPage() {
  useRequireAuth();
  const { data: scans, isLoading } = useQuery({ queryKey: ["scans", "mine"], queryFn: api.listScans });

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Scans</h1>
        <Link href="/scans/new">
          <Button>
            <Plus className="h-4 w-4" />
            New scan
          </Button>
        </Link>
      </div>

      <Card className="mt-6">
        <CardContent className="p-0">
          {isLoading && <p className="px-5 py-4 text-sm text-muted-foreground">Loading…</p>}
          {!isLoading && (scans?.length ?? 0) === 0 && (
            <p className="px-5 py-4 text-sm text-muted-foreground">No scans yet.</p>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-5 py-2 font-medium">Domain</th>
                <th className="px-5 py-2 font-medium">Status</th>
                <th className="px-5 py-2 font-medium">Max pages</th>
                <th className="px-5 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(scans ?? []).map((scan) => (
                <tr key={scan.id} className="hover:bg-muted">
                  <td className="px-5 py-3">
                    <Link href={`/scans/${scan.id}`} className="font-medium hover:underline">
                      {scan.normalized_domain}
                    </Link>
                    {scan.is_demo && <span className="ml-2 text-xs text-muted-foreground">(demo)</span>}
                  </td>
                  <td className="px-5 py-3">
                    <ScanStatusBadge status={scan.status} />
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">{scan.max_pages}</td>
                  <td className="px-5 py-3 text-muted-foreground">{formatDateTime(scan.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </AppShell>
  );
}
