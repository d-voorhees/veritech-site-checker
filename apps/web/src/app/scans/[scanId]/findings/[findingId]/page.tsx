"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Badge, severityToVariant } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { formatDateTime, titleCase } from "@/lib/utils";

export default function FindingDetailPage({
  params,
}: {
  params: Promise<{ scanId: string; findingId: string }>;
}) {
  const { scanId, findingId } = use(params);
  useRequireAuth();

  const { data: findings, isLoading } = useQuery({
    queryKey: ["scan-findings", scanId],
    queryFn: () => api.getScanFindings(scanId),
  });

  const finding = findings?.find((f) => f.id === findingId);

  return (
    <AppShell>
      <Link
        href={`/scans/${scanId}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to scan
      </Link>

      {isLoading && <p className="mt-4 text-sm text-muted-foreground">Loading…</p>}
      {!isLoading && !finding && <p className="mt-4 text-sm text-muted-foreground">Finding not found.</p>}

      {finding && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={severityToVariant(finding.severity)}>{finding.severity}</Badge>
            <Badge variant="outline">confidence: {finding.confidence}</Badge>
            <Badge variant="outline">{titleCase(finding.category)}</Badge>
            {finding.dollar_impact !== "n/a" && <Badge variant="outline">impact: {finding.dollar_impact}</Badge>}
            {finding.remediation_timing !== "n/a" && <Badge variant="outline">{finding.remediation_timing}</Badge>}
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight">{finding.title}</h1>

          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Impact (observation → interpretation)</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed">{finding.impact}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Recommended next step</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed">{finding.recommended_next_step}</p>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Linked evidence ({finding.evidence.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y divide-border">
                {finding.evidence.map((e) => (
                  <li key={e.id} className="px-5 py-4">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <Badge variant="outline">{e.category}</Badge>
                      <Badge variant="outline">{e.source_type}</Badge>
                      <Badge variant="outline">confidence: {e.confidence}</Badge>
                      <span className="text-muted-foreground">captured {formatDateTime(e.captured_at)}</span>
                    </div>
                    <p className="mt-2 text-sm">{e.human_readable_summary}</p>
                    <p className="mt-1 break-all text-xs text-muted-foreground">
                      Source: {e.source_url_or_identifier}
                    </p>
                    {Object.keys(e.normalized_payload_json).length > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                          Normalized evidence payload
                        </summary>
                        <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">
                          {JSON.stringify(e.normalized_payload_json, null, 2)}
                        </pre>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
