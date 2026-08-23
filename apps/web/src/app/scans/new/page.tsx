"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { cn } from "@/lib/utils";

// Mirrors packages/shared/src/constants.ts (AUTHORIZATION_ACKNOWLEDGMENT_TEXT,
// MAX_PAGES_OPTIONS) — see packages/shared/README.md for why this isn't a
// direct import yet.
const AUTHORIZATION_TEXT =
  "I confirm that I own this domain or am authorized to analyze its publicly available content.";

const MAX_PAGES_OPTIONS = [10, 25, 50] as const;

export default function NewScanPage() {
  useRequireAuth();
  const router = useRouter();
  const [targetInput, setTargetInput] = useState("");
  const [notes, setNotes] = useState("");
  const [maxPages, setMaxPages] = useState<10 | 25 | 50>(10);
  const [acknowledged, setAcknowledged] = useState(false);

  const createScan = useMutation({
    mutationFn: () =>
      api.createScan({
        target_input: targetInput,
        notes,
        max_pages: maxPages,
        authorization_acknowledgment: acknowledged,
      }),
    onSuccess: (scan) => router.push(`/scans/${scan.id}`),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-xl">
        <h1 className="text-xl font-semibold tracking-tight">New scan</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Enter a public domain to generate a Technical Acquisition Brief. This is a bounded, rate-limited,
          public-web evidence collector — not a vulnerability scanner or penetration test.
        </p>

        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Scan target</CardTitle>
            <CardDescription>example.com or https://example.com</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-5"
              onSubmit={(e) => {
                e.preventDefault();
                createScan.mutate();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="target">Domain or URL</Label>
                <Input
                  id="target"
                  required
                  placeholder="example.com"
                  value={targetInput}
                  onChange={(e) => setTargetInput(e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="notes">Business / acquisition notes (optional)</Label>
                <Textarea
                  id="notes"
                  placeholder="Context for this pre-screen — deal stage, specific concerns, etc."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>Crawl depth</Label>
                <div className="flex gap-2">
                  {MAX_PAGES_OPTIONS.map((option) => (
                    <button
                      type="button"
                      key={option}
                      onClick={() => setMaxPages(option)}
                      className={cn(
                        "flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                        maxPages === option
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background hover:bg-muted"
                      )}
                    >
                      {option} pages
                    </button>
                  ))}
                </div>
              </div>

              <label className="flex items-start gap-2.5 rounded-md border border-border bg-muted/50 p-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                  required
                />
                <span>{AUTHORIZATION_TEXT}</span>
              </label>

              {createScan.isError && (
                <p className="text-sm text-red-600">
                  {createScan.error instanceof ApiError
                    ? String(createScan.error.detail)
                    : "Could not create scan."}
                </p>
              )}

              <Button type="submit" disabled={createScan.isPending || !acknowledged}>
                {createScan.isPending ? "Starting scan…" : "Start scan"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
