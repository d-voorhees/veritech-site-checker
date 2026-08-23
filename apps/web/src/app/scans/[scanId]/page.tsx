"use client";

import Link from "next/link";
import { use, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Download, Loader2, XCircle } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ScanStatusBadge } from "@/components/status-badge";
import { Badge, severityToVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, exportHtmlUrl } from "@/lib/api";
import { gtmPush } from "@/lib/gtm";
import { useRequireAuth } from "@/lib/use-auth";
import { cn, formatDateTime, formatDuration, titleCase } from "@/lib/utils";

const ACTIVE_STATUSES = new Set(["queued", "starting", "running"]);

// What each collection task feeds into, mirrored from the rules engine's
// static RULE_CATALOG (apps/api/app/rules/definitions.py) so this list
// reads as "what does this task investigate" rather than a raw pipeline
// stage name — the two must be kept in sync if rules move between tasks.
const TASK_AREA_MAP: Record<string, string> = {
  http_checks: "Security posture — HTTPS, HSTS, CSP headers, TLS certificate expiration",
  robots_sitemap: "Discoverability and platform exposure — sitemap presence, WordPress xmlrpc.php and REST API exposure",
  crawl: "Indexability, on-page SEO, site reliability — canonical tag, meta description, crawl errors",
  dns_email_posture: "Email deliverability and domain registration — SPF, DMARC, DKIM, domain expiration",
  browser_render: "Dependency management, accessibility, security posture — third-party request domains, image alt text, form labels, mixed content",
  technology_detection: "Technology stack identification and analytics detection — tech stack, plus the analytics/tag-manager check",
  performance: "Performance — mobile PageSpeed score",
  rules_engine: "Evaluates evidence from every task above and produces findings",
};

export default function ScanDetailPage({ params }: { params: Promise<{ scanId: string }> }) {
  const { scanId } = use(params);
  useRequireAuth();

  const scanQuery = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => api.getScan(scanId),
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 3000 : false),
  });

  const reportQuery = useQuery({
    queryKey: ["scan-report", scanId],
    queryFn: () => api.getScanReport(scanId),
    enabled: !!scanQuery.data,
    refetchInterval: () => (scanQuery.data && ACTIVE_STATUSES.has(scanQuery.data.status) ? 3000 : false),
  });

  const eventsQuery = useQuery({
    queryKey: ["scan-events", scanId],
    queryFn: () => api.getScanEvents(scanId),
    enabled: !!scanQuery.data,
    refetchInterval: () => (scanQuery.data && ACTIVE_STATUSES.has(scanQuery.data.status) ? 3000 : false),
  });

  const scan = scanQuery.data;
  const report = reportQuery.data;

  const rulesJobStatus = scan?.jobs.find((j) => j.task_name === "rules_engine")?.status;
  const reportReady = !!report && rulesJobStatus !== "pending" && rulesJobStatus !== "running" && rulesJobStatus !== undefined;
  const reportReadyFired = useRef(false);
  useEffect(() => {
    if (reportReady && !reportReadyFired.current) {
      reportReadyFired.current = true;
      gtmPush({ event: "sitecheck_completed", report_type: "website_audit" });
    }
  }, [reportReady]);

  if (scanQuery.isLoading || !scan) {
    return (
      <AppShell>
        <p className="text-sm text-muted-foreground">Loading scan…</p>
      </AppShell>
    );
  }

  const isActive = ACTIVE_STATUSES.has(scan.status);

  const jobStatusByTask = new Map(scan.jobs.map((j) => [j.task_name, j.status]));
  const isTaskPending = (taskName: string) => {
    const status = jobStatusByTask.get(taskName);
    return status === "pending" || status === "running" || status === undefined;
  };
  const rulesPending = isTaskPending("rules_engine");

  return (
    <AppShell>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{scan.normalized_domain}</h1>
            <ScanStatusBadge status={scan.status} />
            {scan.is_demo && <Badge variant="outline">Synthetic demo data</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Technical Acquisition Brief</p>
        </div>
        <a href={exportHtmlUrl(scan.id)} target="_blank" rel="noreferrer">
          <Button variant="outline">
            <Download className="h-4 w-4" />
            Export HTML report
          </Button>
        </a>
      </div>

      {scan.failure_summary && (
        <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {scan.failure_summary}
        </div>
      )}

      {report && !rulesPending && report.coverage.state !== "full" && (
        <CoverageBanner coverage={report.coverage as { state: string; message: string; detail?: string }} />
      )}

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetaItem label="Authorization confirmed" value={formatDateTime(scan.authorization_confirmed_at)} />
        <MetaItem label="Started" value={formatDateTime(scan.started_at)} />
        <MetaItem label="Completed" value={formatDateTime(scan.completed_at)} />
        <MetaItem label="Pages scanned" value={`${report?.pages_scanned ?? "—"} (max ${scan.max_pages})`} />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Scan Collection tasks</CardTitle>
          <CardDescription>
            Each task runs independently — one failure does not fail the whole scan. Together they feed the
            checks the rules engine evaluates below.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {scan.jobs.map((job) => (
              <li key={job.id} className="flex items-start justify-between gap-4 px-5 py-2.5 text-sm">
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5">
                    <TaskStatusIcon status={job.status} />
                  </span>
                  <div>
                    <div>{titleCase(job.task_name)}</div>
                    {TASK_AREA_MAP[job.task_name] && (
                      <div className="mt-0.5 text-xs text-muted-foreground">{TASK_AREA_MAP[job.task_name]}</div>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3 whitespace-nowrap text-xs text-muted-foreground">
                  {job.error_message && <span className="max-w-xs truncate text-red-600">{job.error_message}</span>}
                  <span className="tabular-nums">{formatDuration(job.started_at, job.finished_at)}</span>
                  <span className="capitalize">{job.status}</span>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
        {scan.started_at && scan.completed_at && (
          <div className="flex items-center justify-between border-t border-border px-5 py-2.5 text-sm font-medium">
            <span>Total report generation time</span>
            <span className="tabular-nums">{formatDuration(scan.started_at, scan.completed_at)}</span>
          </div>
        )}
      </Card>

      {isActive && eventsQuery.data && eventsQuery.data.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Live activity</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              {eventsQuery.data.slice(-10).map((event) => (
                <li key={event.id}>
                  <span className="font-mono">{formatDateTime(event.created_at)}</span> — {event.message}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {report && (
        <>
          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Risk summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-3">
                <SeverityTile label="High" count={report.severity_counts.high} variant="high" pending={rulesPending} />
                <SeverityTile
                  label="Medium"
                  count={report.severity_counts.medium}
                  variant="medium"
                  pending={rulesPending}
                />
                <SeverityTile label="Low" count={report.severity_counts.low} variant="low" pending={rulesPending} />
                <SeverityTile label="Info" count={report.severity_counts.info} variant="info" pending={rulesPending} />
              </div>
            </CardContent>
          </Card>

          <RulesCoverageSection rulesChecked={report.rules_checked} pending={rulesPending} />

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Prioritized risk register</CardTitle>
              <CardDescription>
                Findings distinguish observation from interpretation and hardening opportunities from confirmed
                vulnerabilities — this product does not confirm vulnerabilities.{" "}
                <a href="#legend" className="underline">
                  What do severity, confidence, dollar impact, and remediation timing mean?
                </a>
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {rulesPending ? (
                <PendingNotice label="the rules engine" padded />
              ) : report.findings.length === 0 ? (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  No findings were raised by the rules engine for the evidence collected.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="px-5 py-2 font-medium">Severity</th>
                        <th className="px-5 py-2 font-medium">Finding</th>
                        <th className="px-5 py-2 font-medium">Category</th>
                        <th className="px-5 py-2 font-medium">Confidence</th>
                        <th className="px-5 py-2 font-medium">$ impact</th>
                        <th className="px-5 py-2 font-medium">Remediation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {report.findings.map((finding) => (
                        <tr key={finding.id} className="hover:bg-muted">
                          <td className="px-5 py-3">
                            <Badge variant={severityToVariant(finding.severity)}>{finding.severity}</Badge>
                          </td>
                          <td className="px-5 py-3">
                            <Link href={`/scans/${scan.id}/findings/${finding.id}`} className="font-medium hover:underline">
                              {finding.title}
                            </Link>
                          </td>
                          <td className="px-5 py-3 text-muted-foreground">{titleCase(finding.category)}</td>
                          <td className="px-5 py-3 text-muted-foreground capitalize">{finding.confidence}</td>
                          <td className="px-5 py-3 text-muted-foreground">
                            {finding.dollar_impact !== "n/a" ? finding.dollar_impact : "—"}
                          </td>
                          <td className="px-5 py-3 text-muted-foreground whitespace-nowrap">
                            {finding.remediation_timing !== "n/a" ? finding.remediation_timing : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <SeverityConfidenceLegend />

          <SectionHeading
            title="Business continuity"
            description="Will this site still be here in 60 days? Domain registration, TLS certificate, and how a visitor actually reaches the homepage."
          />
          <DomainAndCertificateSection
            domainRegistration={report.domain_registration}
            tls={report.tls}
            pending={isTaskPending("dns_email_posture")}
          />
          <AvailabilitySection httpSecurity={report.http_security} pending={isTaskPending("http_checks")} />

          <SectionHeading title="Platform and stack" description="What is this business built on, and what would a buyer be inheriting?" />
          <PlatformSection technology={report.technology} httpSecurity={report.http_security} pending={isTaskPending("technology_detection")} />
          <TechnologySection technology={report.technology} pending={isTaskPending("technology_detection")} />
          <ThirdPartyDependenciesSection
            thirdPartyDependencies={report.third_party_dependencies}
            pending={isTaskPending("browser_render")}
          />
          <PlatformExposureSection platformExposure={report.platform_exposure} pending={isTaskPending("robots_sitemap")} />

          <HttpSection httpSecurity={report.http_security} pending={isTaskPending("http_checks")} />
          <CrawlSection
            crawl={report.crawl_indexability}
            maxPages={scan.max_pages}
            pending={isTaskPending("crawl")}
          />
          <DnsSection dnsEmail={report.dns_email} pending={isTaskPending("dns_email_posture")} />
          <PerformanceSection performance={report.performance} pending={isTaskPending("performance")} />
          <AccessibilitySection accessibility={report.accessibility} pending={isTaskPending("browser_render")} />

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Known limitations of this scan</CardTitle>
              <CardDescription>{report.scope_statement}</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
                {report.limitations.map((l, i) => (
                  <li key={i}>
                    {l.task_name && <span className="font-medium text-foreground">{titleCase(l.task_name)}: </span>}
                    {l.message}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <div className="mt-10 border-t border-border pt-8">
            <p className="text-sm text-muted-foreground">
              This scan gives you a first read. For a full technical review before you close, see the checklist or
              book a nine-layer review.
            </p>
            <div className="mt-3 flex flex-wrap gap-6">
              <a
                href="https://veritechdiligence.com/what-to-check-before-you-buy-a-web-based-business/"
                className="btn-secondary"
              >
                Read the checklist <span className="arrow">→</span>
              </a>
              <a
                href="https://veritechdiligence.com/#contact"
                className="btn-secondary"
                onClick={() => gtmPush({ event: "contact_click" })}
              >
                Book the nine-layer review <span className="arrow">→</span>
              </a>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}

function SectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="mt-8">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function SeverityConfidenceLegend() {
  return (
    <details id="legend" className="mt-4 rounded-md border border-border bg-muted/40 px-4 py-3 text-sm">
      <summary className="cursor-pointer font-medium">
        Severity, confidence, dollar impact &amp; remediation timing — legend
      </summary>
      <div className="mt-2 flex flex-col gap-2 text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">Severity</span> (high / medium / low / info) is how much
          this finding matters on its own if nothing else changes — high means a real, current problem (e.g. no
          HTTPS); info means worth knowing but not urgent on its own.
        </p>
        <p>
          <span className="font-medium text-foreground">Confidence</span> (high / medium / low) is how sure this
          scan is that the finding is real, given what it could observe — lower confidence usually means the check
          is a best-effort probe (e.g. DKIM selector discovery only checks common defaults) rather than exhaustive.
        </p>
        <p>
          <span className="font-medium text-foreground">Dollar impact</span> ($ / $$ / $$$) is a rough,
          rule-assigned band for how much this is worth caring about financially — never an exact number. For a
          few findings (domain/TLS expiration) the band reflects the risk of inaction rather than the small direct
          fix cost.
        </p>
        <p>
          <span className="font-medium text-foreground">Remediation timing</span> (30-day / 60-day / 90-day /
          longer-term) is the rule&rsquo;s suggested urgency for addressing the finding.
        </p>
      </div>
    </details>
  );
}

function CoverageBanner({ coverage }: { coverage: { state: string; message: string; detail?: string } }) {
  const isBlocked = coverage.state === "blocked";
  return (
    <div
      className={cn(
        "mt-4 rounded-md border-2 px-4 py-3 text-sm",
        isBlocked ? "border-red-400 bg-red-50 text-red-900" : "border-amber-400 bg-amber-50 text-amber-900"
      )}
    >
      <div className="flex items-center gap-2 font-semibold uppercase tracking-wide">
        <Badge variant={isBlocked ? "high" : "medium"}>{isBlocked ? "Blocked" : "Partial coverage"}</Badge>
        {coverage.message}
      </div>
      {coverage.detail && <p className="mt-1.5 text-sm">{coverage.detail}</p>}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  );
}

function SeverityTile({
  label,
  count,
  variant,
  pending,
}: {
  label: string;
  count: number;
  variant: "high" | "medium" | "low" | "info";
  pending: boolean;
}) {
  return (
    <div className="rounded-md border border-border p-4 text-center">
      <div className={cn("text-2xl font-semibold")}>{pending ? "—" : count}</div>
      <Badge variant={variant} className="mt-1">
        {label}
      </Badge>
    </div>
  );
}

function PendingNotice({ label, padded = false }: { label: string; padded?: boolean }) {
  return (
    <p className={cn("flex items-center gap-2 text-sm text-muted-foreground", padded && "px-5 py-4")}>
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      Pending — {label} hasn&rsquo;t finished collecting yet.
    </p>
  );
}

function RulesCoverageSection({
  rulesChecked,
  pending,
}: {
  rulesChecked: { total_count: number; fired_count: number; rules: Array<Record<string, unknown>> };
  pending: boolean;
}) {
  const rules = rulesChecked.rules ?? [];
  return (
    <Card className="mt-6 p-0">
      <details>
        <summary className="cursor-pointer list-none px-5 py-4">
          <div className="text-base font-semibold tracking-tight">All checks &amp; findings</div>
          <div className="mt-1 text-sm text-muted-foreground">
            {pending
              ? "This runs last, after all other scan collection tasks finish, so the outcomes below are not final yet."
              : `${rulesChecked.total_count} rules checked, ${rulesChecked.fired_count} raised a finding or observation — expand for the full list.`}
          </div>
        </summary>
        <div className="border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-5 py-2 font-medium">Category</th>
                <th className="px-5 py-2 font-medium">Check</th>
                <th className="px-5 py-2 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.map((r) => (
                <tr key={String(r.rule_key)}>
                  <td className="px-5 py-2 text-muted-foreground">{String(r.category).replace(/_/g, " ")}</td>
                  <td className="px-5 py-2">{String(r.check)}</td>
                  <td className="px-5 py-2">
                    {r.fired && r.positive_observation ? (
                      <span className="inline-flex items-center gap-2">
                        <Badge variant="success">positive</Badge>
                        {String(r.title)}
                      </span>
                    ) : r.fired ? (
                      <span className="inline-flex items-center gap-2">
                        <Badge variant={severityToVariant(String(r.severity))}>{String(r.severity)}</Badge>
                        {String(r.title)}
                      </span>
                    ) : pending ? (
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Pending
                      </span>
                    ) : (
                      <span className="text-muted-foreground">OK</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

function TaskStatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-600" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-amber-600" />;
  return <CircleDashed className="h-4 w-4 text-muted-foreground" />;
}

function DnsSection({ dnsEmail, pending }: { dnsEmail: Record<string, unknown>; pending: boolean }) {
  const spf = dnsEmail.spf as { record?: string | null } | null;
  const dmarc = dnsEmail.dmarc as { record?: string | null; policy?: string | null } | null;
  const dkimSelectorsFound = (dnsEmail.dkim_selectors_found as string[] | undefined) ?? [];
  const dkimProbedCount = Number(dnsEmail.dkim_probed_count ?? 0);
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Email posture</CardTitle>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="DNS and email posture" />
        ) : (
        <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">SPF</dt>
            <dd className="mt-0.5 break-words">{spf?.record ?? "Not present"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">DMARC</dt>
            <dd className="mt-0.5 break-words">
              {dmarc?.record ?? "Not present"}
              {dmarc?.policy ? ` (policy: ${dmarc.policy})` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">DKIM</dt>
            <dd className="mt-0.5 break-words">
              {dkimSelectorsFound.length > 0
                ? `Found under selector${dkimSelectorsFound.length > 1 ? "s" : ""}: ${dkimSelectorsFound.join(", ")}`
                : `Not found under ${dkimProbedCount} commonly probed selectors (not proof of absence)`}
            </dd>
          </div>
        </dl>
        )}
      </CardContent>
    </Card>
  );
}

function DomainAndCertificateSection({
  domainRegistration,
  tls,
  pending,
}: {
  domainRegistration: Record<string, unknown>;
  tls: Record<string, unknown>;
  pending: boolean;
}) {
  const hasDomain = domainRegistration && domainRegistration.expiration_date != null;
  const hasTls = tls && tls.not_after != null;
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Domain and certificate</CardTitle>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="domain and certificate checks" />
        ) : (
          <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Domain registration</dt>
              <dd className="mt-0.5 break-words">
                {hasDomain ? (
                  <>
                    Registrar: {String(domainRegistration.registrar ?? "unknown")} · expires{" "}
                    {String(domainRegistration.expiration_date)}
                    {domainRegistration.days_until_expiration != null
                      ? ` (${domainRegistration.days_until_expiration} day(s))`
                      : ""}
                  </>
                ) : (
                  "Not available for this scan."
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">TLS certificate</dt>
              <dd className="mt-0.5 break-words">
                {hasTls ? (
                  <>
                    Issuer: {String(tls.issuer ?? "unknown")} · expires {String(tls.not_after)}
                    {tls.days_until_expiry != null ? ` (${tls.days_until_expiry} day(s))` : ""}
                  </>
                ) : (
                  "Not available for this scan."
                )}
              </dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function AvailabilitySection({
  httpSecurity,
  pending,
}: {
  httpSecurity: Record<string, unknown>;
  pending: boolean;
}) {
  const redirectChain = (httpSecurity.redirect_chain as Array<Record<string, unknown>> | undefined) ?? [];
  const hopCount = Number(httpSecurity.redirect_hop_count ?? redirectChain.length);
  const worthFlagging = Boolean(httpSecurity.redirect_worth_flagging);
  const mixesSchemes = Boolean(httpSecurity.redirect_mixes_schemes);
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Availability</CardTitle>
      </CardHeader>
      <CardContent>
        {pending || !httpSecurity.final_url ? (
          <PendingNotice label="HTTP availability checks" />
        ) : (
          <>
            <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Final URL</dt>
                <dd className="mt-0.5 break-words">{String(httpSecurity.final_url)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Status code</dt>
                <dd className="mt-0.5">{String(httpSecurity.status_code ?? "—")}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">HTTPS</dt>
                <dd className="mt-0.5">{httpSecurity.is_https ? "Yes" : "No"}</dd>
              </div>
            </dl>
            <div className="mt-4">
              <p className="flex items-center gap-2 text-sm font-medium">
                Redirect chain ({hopCount} hop{hopCount === 1 ? "" : "s"})
                {worthFlagging && <Badge variant="high">worth a look</Badge>}
              </p>
              {redirectChain.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">
                  No redirects — the requested URL was served directly.
                </p>
              ) : (
                <ul className="mt-1.5 flex flex-col gap-1 text-sm">
                  {redirectChain.map((hop, i) => (
                    <li key={i} className="border-l-2 border-border pl-2">
                      {String(hop.from_url)} <span className="font-medium">&rarr; {String(hop.status_code)} &rarr;</span>{" "}
                      {String(hop.to_url)}
                    </li>
                  ))}
                  <li className="border-l-2 border-border pl-2 text-muted-foreground">
                    {String(httpSecurity.final_url)} (final)
                  </li>
                </ul>
              )}
              {mixesSchemes && (
                <p className="mt-1.5 text-xs text-red-600">
                  This chain crosses http/https — worth confirming every intermediate hop is intentional.
                </p>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function PlatformSection({
  technology,
  httpSecurity,
  pending,
}: {
  technology: { platform?: Record<string, unknown> | null };
  httpSecurity: Record<string, unknown>;
  pending: boolean;
}) {
  const platform = technology.platform ?? null;
  const hostingFingerprint = (httpSecurity.hosting_fingerprint as Record<string, string> | undefined) ?? {};
  const hasFingerprint = Object.keys(hostingFingerprint).length > 0;
  if (pending) {
    return (
      <Card className="mt-4">
        <CardContent className="pt-4">
          <PendingNotice label="platform detection" />
        </CardContent>
      </Card>
    );
  }
  return (
    <Card className="mt-4">
      <CardContent className="pt-4">
        {platform ? (
          <div className="rounded-md border border-border bg-muted/40 p-3">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Platform</div>
            <div className="mt-0.5 text-base font-semibold">{String(platform.name)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {String(platform.detection_method)}
              {platform.heuristic ? " (inferred from crawled URL patterns, not an explicit platform marker)" : ""}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No CMS, ecommerce platform, website builder, headless CMS, or static-site framework could be identified
            from the evidence collected.
          </p>
        )}
        {hasFingerprint && (
          <dl className="mt-4 grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            {Object.entries(hostingFingerprint).map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
                <dd className="mt-0.5 break-words">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function PlatformExposureSection({
  platformExposure,
  pending,
}: {
  platformExposure: Record<string, unknown>;
  pending: boolean;
}) {
  const xmlrpc = platformExposure?.xmlrpc as Record<string, unknown> | undefined;
  const wpJson = platformExposure?.wp_json as Record<string, unknown> | undefined;
  const hasData = Boolean(xmlrpc || wpJson);
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Platform exposure</CardTitle>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="platform exposure probes" />
        ) : !hasData ? (
          <p className="text-sm text-muted-foreground">No platform-specific exposure probes recorded for this scan.</p>
        ) : (
          <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">xmlrpc.php</dt>
              <dd className="mt-0.5">{xmlrpc ? `HTTP ${xmlrpc.status_code ?? "error"}` : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">wp-json REST API root</dt>
              <dd className="mt-0.5">{wpJson ? `HTTP ${wpJson.status_code ?? "error"}` : "—"}</dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function ThirdPartyDependenciesSection({
  thirdPartyDependencies,
  pending,
}: {
  thirdPartyDependencies: { domains: Array<Record<string, unknown>>; hostname_count?: number };
  pending: boolean;
}) {
  const domains = thirdPartyDependencies.domains ?? [];
  const hostnameCount = thirdPartyDependencies.hostname_count ?? domains.length;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Third-party dependencies</CardTitle>
        <CardDescription>
          {pending
            ? "Waiting on browser rendering to finish."
            : `${hostnameCount} distinct third-party request domain(s) observed while rendering the homepage.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="third-party dependency collection" />
        ) : domains.length === 0 ? (
          <p className="text-sm text-muted-foreground">No third-party request domains were observed.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1 pr-4 font-medium">Hostname</th>
                  <th className="py-1 pr-4 font-medium">Vendor</th>
                  <th className="py-1 pr-4 font-medium">Category</th>
                  <th className="py-1 font-medium">Requests</th>
                </tr>
              </thead>
              <tbody>
                {domains.map((d) => (
                  <tr key={String(d.hostname)} className="border-t">
                    <td className="py-1 pr-4 break-all">{String(d.hostname)}</td>
                    <td className="py-1 pr-4">{String(d.vendor_name ?? "—")}</td>
                    <td className="py-1 pr-4">{String(d.category ?? "—").replace(/_/g, " ")}</td>
                    <td className="py-1">{String(d.request_count ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HttpSection({
  httpSecurity,
  pending,
}: {
  httpSecurity: Record<string, unknown>;
  pending: boolean;
}) {
  const mixedContentCount = Number(httpSecurity.mixed_content_count ?? 0);
  const entries: Array<[string, string]> = [
    ["Strict-Transport-Security", String(httpSecurity.strict_transport_security ?? "Not present")],
    ["Content-Security-Policy", String(httpSecurity.content_security_policy ?? "Not present")],
    ["X-Frame-Options", String(httpSecurity.x_frame_options ?? "Not present")],
    ["Referrer-Policy", String(httpSecurity.referrer_policy ?? "Not present")],
    ["Mixed content (HTTP on HTTPS)", mixedContentCount > 0 ? `${mixedContentCount} request(s)` : "None observed"],
  ];
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>HTTP and security headers</CardTitle>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="HTTP and security header checks" />
        ) : (
          <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
            {entries.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
                <dd className="mt-0.5 break-words">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function UrlSampleList({
  title,
  note,
  count,
  sample,
}: {
  title: string;
  note: string;
  count: number;
  sample: string[];
}) {
  return (
    <div className="mt-4">
      <p className="text-sm font-medium">
        {title} ({count})
      </p>
      <p className="text-xs text-muted-foreground">{note}</p>
      {sample.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">None.</p>
      ) : (
        <ul className="mt-1 list-inside list-disc text-sm">
          {sample.map((u) => (
            <li key={u} className="break-all">
              {u}
            </li>
          ))}
          {count > sample.length && <li className="text-muted-foreground">… and {count - sample.length} more</li>}
        </ul>
      )}
    </div>
  );
}

function CrawlSection({
  crawl,
  maxPages,
  pending,
}: {
  crawl: Record<string, unknown>;
  maxPages: number;
  pending: boolean;
}) {
  const pages = (crawl.pages as Array<Record<string, unknown>>) ?? [];
  const sc = (crawl.sitemap_check as Record<string, unknown>) ?? {};
  const disallowRules = (sc.disallow_rules as string[] | undefined) ?? [];
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Crawl and indexability</CardTitle>
        <CardDescription>
          {pending
            ? "Crawl in progress."
            : `${String(crawl.pages_scanned ?? 0)} pages scanned; ${String(crawl.error_page_count ?? 0)} returned a 4xx/5xx status.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {pending ? (
          <PendingNotice label="the crawl" padded />
        ) : (
        <>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-5 py-2 font-medium">URL</th>
              <th className="px-5 py-2 font-medium">Status</th>
              <th className="px-5 py-2 font-medium">Title</th>
              <th className="px-5 py-2 font-medium">Canonical</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {pages.map((p, i) => (
              <tr key={i}>
                <td className="max-w-xs truncate px-5 py-2">{String(p.url)}</td>
                <td className="px-5 py-2">{String(p.status_code ?? "error")}</td>
                <td className="max-w-xs truncate px-5 py-2 text-muted-foreground">{String(p.title ?? "—")}</td>
                <td className="px-5 py-2 text-muted-foreground">{p.canonical_url ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="border-t border-border px-5 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Checked against robots.txt and sitemap
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Sitemap URLs declared</dt>
              <dd className="mt-0.5">
                {String(sc.sitemap_declared_count ?? 0)} URL(s) across {String(sc.sitemap_file_count ?? 0)} sitemap
                file(s)
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                Robots.txt Disallow rules (User-agent: *)
              </dt>
              <dd className="mt-0.5 break-words">
                {disallowRules.length > 0 ? disallowRules.join(", ") : "No Disallow rules declared"}
              </dd>
            </div>
            {Number(sc.lastmod_count ?? 0) > 0 && (
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Sitemap freshness</dt>
                <dd className="mt-0.5 break-words">
                  Newest: {String(sc.newest_lastmod)} · Oldest: {String(sc.oldest_lastmod)} (across{" "}
                  {String(sc.lastmod_count)} entr{Number(sc.lastmod_count) === 1 ? "y" : "ies"} with a &lt;lastmod&gt;
                  date)
                </dd>
              </div>
            )}
          </dl>

          <UrlSampleList
            title="Crawled but not declared in sitemap"
            note="Pages this scan reached that the sitemap doesn't list — often fine (new content, legal pages), but worth confirming they're intentional."
            count={Number(sc.crawled_not_in_sitemap_count ?? 0)}
            sample={(sc.crawled_not_in_sitemap_sample as string[] | undefined) ?? []}
          />
          <UrlSampleList
            title="Declared in sitemap but not reached by this crawl"
            note={`This scan is bounded to ${maxPages} pages, so this may just reflect that budget rather than a site defect.`}
            count={Number(sc.sitemap_not_crawled_count ?? 0)}
            sample={(sc.sitemap_not_crawled_sample as string[] | undefined) ?? []}
          />
          {disallowRules.length > 0 && (
            <UrlSampleList
              title="Crawled despite matching a robots.txt Disallow rule"
              note="Informational only — this scan does not enforce robots.txt, so this shows where the site's stated crawl preferences and its actual reachable content diverge."
              count={Number(sc.crawled_but_disallowed_count ?? 0)}
              sample={(sc.crawled_but_disallowed_sample as string[] | undefined) ?? []}
            />
          )}
        </div>
        </>
        )}
      </CardContent>
    </Card>
  );
}

function TechnologySection({
  technology,
  pending,
}: {
  technology: { technologies: Array<Record<string, unknown>> };
  pending: boolean;
}) {
  const items = technology.technologies ?? [];

  const byCategory = new Map<string, Array<Record<string, unknown>>>();
  for (const t of items) {
    const category = String(t.category);
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category)!.push(t);
  }
  const categories = [...byCategory.keys()].sort();

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Technology and dependencies</CardTitle>
        {!pending && items.length > 0 && (
          <CardDescription>
            {items.length} {items.length === 1 ? "technology" : "technologies"} identified across {categories.length}{" "}
            {categories.length === 1 ? "category" : "categories"}.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="technology detection" />
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No technologies were positively identified.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {categories.map((category) => (
              <div key={category}>
                <div className="eyebrow mb-2 text-muted-foreground">{titleCase(category)}</div>
                <div className="flex flex-wrap gap-2">
                  {byCategory.get(category)!.map((t, i) => (
                    <Badge key={i} variant="outline" className="tech-pill" title={String(t.detection_method)}>
                      {String(t.technology_name)}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type PageSpeedStrategy = {
  performance_score?: number | null;
  accessibility_score?: number | null;
  best_practices_score?: number | null;
  seo_score?: number | null;
  lcp_ms?: number | null;
  fcp_ms?: number | null;
  ttfb_ms?: number | null;
};

function PerformanceSection({ performance, pending }: { performance: Record<string, unknown>; pending: boolean }) {
  const desktop = performance.desktop as PageSpeedStrategy | undefined;
  const mobile = performance.mobile as PageSpeedStrategy | undefined;
  const configured = performance.configured !== false;

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Page speed performance</CardTitle>
        {!pending && !configured && (
          <CardDescription>Google PageSpeed Insights was not configured; local measurements only.</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="performance measurement" />
        ) : (
        <>
        <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Response time</dt>
            <dd className="mt-0.5">{String(performance.response_duration_ms ?? "—")} ms</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">HTML size</dt>
            <dd className="mt-0.5">{String(performance.html_bytes ?? "—")} bytes</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Third-party domains</dt>
            <dd className="mt-0.5">{String(performance.third_party_domain_count ?? "—")}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">JS requests</dt>
            <dd className="mt-0.5">{String(performance.js_resource_count ?? "—")}</dd>
          </div>
        </dl>

        {configured && desktop && mobile && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1 pr-4 font-medium">Google PageSpeed Insights</th>
                  <th className="py-1 pr-4 font-medium">Desktop</th>
                  <th className="py-1 font-medium">Mobile</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["Performance score", "performance_score", ""],
                    ["Accessibility score", "accessibility_score", ""],
                    ["Best practices score", "best_practices_score", ""],
                    ["SEO score", "seo_score", ""],
                    ["LCP", "lcp_ms", "ms", true],
                    ["FCP", "fcp_ms", "ms", true],
                    ["TTFB", "ttfb_ms", "ms", false],
                  ] as [string, keyof PageSpeedStrategy, string, boolean][]
                ).map(([label, key, unit, round3]) => (
                  <tr key={key} className="border-t">
                    <td className="py-1 pr-4">{label}</td>
                    <td className="py-1 pr-4">
                      {desktop[key] != null ? `${round3 ? Number(desktop[key]).toFixed(3) : desktop[key]}${unit}` : "—"}
                    </td>
                    <td className="py-1">
                      {mobile[key] != null ? `${round3 ? Number(mobile[key]).toFixed(3) : mobile[key]}${unit}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">
              TTFB above is PageSpeed Insights&rsquo; &ldquo;server response time&rdquo; for the tested resource. A
              very low (near-zero) value usually means the response was served from a CDN edge/cache rather than
              indicating a measurement error.
            </p>
          </div>
        )}
        </>
        )}
      </CardContent>
    </Card>
  );
}

function AccessibilitySection({
  accessibility,
  pending,
}: {
  accessibility: Record<string, unknown>;
  pending: boolean;
}) {
  const hasData = accessibility && accessibility.image_count !== undefined;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Accessibility (homepage)</CardTitle>
        <CardDescription>
          A static pass over the rendered homepage — alt text, form labels, and known overlay-widget scripts. Not a
          substitute for a full manual/automated accessibility audit.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {pending ? (
          <PendingNotice label="the accessibility pass" />
        ) : !hasData ? (
          <p className="text-sm text-muted-foreground">No accessibility data was recorded for this scan.</p>
        ) : (
          <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            {(() => {
              const missingAlt = Number(accessibility.images_missing_alt_count ?? 0);
              const missingLabels = Number(accessibility.fields_missing_labels_count ?? 0);
              return (
                <>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Images with alt text</dt>
                    <dd className="mt-0.5">
                      {Number(accessibility.image_count ?? 0) - missingAlt} of{" "}
                      {String(accessibility.image_count ?? 0)}
                      {missingAlt > 0 && (
                        <span className="ml-1.5 text-red-600">
                          — {missingAlt} missing, needs to be fixed
                        </span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Form fields with labels</dt>
                    <dd className="mt-0.5">
                      {Number(accessibility.labelable_field_count ?? 0) - missingLabels} of{" "}
                      {String(accessibility.labelable_field_count ?? 0)}
                      {missingLabels > 0 && (
                        <span className="ml-1.5 text-red-600">
                          — {missingLabels} missing, needs to be fixed
                        </span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Overlay widget</dt>
                    <dd className="mt-0.5">{String(accessibility.overlay_widget_vendor ?? "None detected")}</dd>
                  </div>
                </>
              );
            })()}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
