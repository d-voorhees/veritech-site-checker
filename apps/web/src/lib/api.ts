// Typed client for the Veritech Scan API. All requests use relative paths
// (/api/v1/...) so the browser never needs to know the API's real origin —
// in production, Next.js rewrites /api/* to the API process running
// alongside it in the same Fly Machine (see next.config.mjs and
// scripts/entrypoint.sh); in local dev, Next.js rewrites do the same
// against API_INTERNAL_URL. This keeps CORS out of the picture entirely.

// In production, NEXT_PUBLIC_API_BASE_URL is unset and this stays relative
// so requests go through the same-origin rewrite in next.config.mjs. In
// local dev there is no rewrite, so this points straight at the API process.
const API_BASE = `${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1`;

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

// --- types (mirrors apps/api/app/schemas) -------------------------------------------

export type ScanStatus =
  | "queued"
  | "starting"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  role: string;
  organization_id: string;
  organization_name: string;
  scans_used_today: number;
  scan_daily_limit: number;
  has_password: boolean;
}

export interface ScanJob {
  id: string;
  task_name: string;
  status: string;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface ScanEvent {
  id: string;
  event_type: string;
  message: string;
  created_at: string;
}

export interface ScanSummary {
  id: string;
  normalized_domain: string;
  status: ScanStatus;
  max_pages: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  is_demo: boolean;
}

export interface ScanDetail extends ScanSummary {
  user_id: string;
  original_input: string;
  notes: string;
  authorization_confirmed_at: string;
  failure_summary: string | null;
  jobs: ScanJob[];
}

export interface EvidenceItem {
  id: string;
  category: string;
  source_type: string;
  source_url_or_identifier: string;
  captured_at: string;
  confidence: "low" | "medium" | "high";
  normalized_payload_json: Record<string, unknown>;
  human_readable_summary: string;
  raw_response_reference: string | null;
}

export interface Finding {
  id: string;
  category: string;
  severity: "ok" | "info" | "low" | "medium" | "high";
  confidence: "low" | "medium" | "high";
  title: string;
  impact: string;
  recommended_next_step: string;
  dollar_impact: string;
  remediation_timing: string;
  status: string;
  rule_version: number;
  created_at: string;
  evidence: EvidenceItem[];
}

export interface ReportOut {
  scan_id: string;
  product_name: string;
  parent_brand: string;
  report_name: string;
  domain: string;
  original_input: string;
  notes: string;
  status: ScanStatus;
  max_pages: number;
  authorization_confirmed_at: string;
  started_at: string | null;
  completed_at: string | null;
  pages_scanned: number;
  is_demo: boolean;
  severity_counts: { high: number; medium: number; low: number; info: number };
  findings: Finding[];
  rules_checked: { total_count: number; fired_count: number; rules: Array<Record<string, unknown>> };
  coverage: { state: "full" | "partial" | "blocked"; message: string; detail?: string; finding_id: string | null };
  dns_email: Record<string, unknown>;
  http_security: Record<string, unknown>;
  crawl_indexability: Record<string, unknown>;
  technology: { platform: Record<string, unknown> | null; technologies: Array<Record<string, unknown>> };
  third_party_dependencies: { domains: Array<Record<string, unknown>> };
  performance: Record<string, unknown>;
  tls: Record<string, unknown>;
  platform_exposure: Record<string, unknown>;
  domain_registration: Record<string, unknown>;
  accessibility: Record<string, unknown>;
  scope_statement: string;
  limitations: Array<{ task_name: string; message: string }>;
  generated_at: string;
}

// --- calls ---------------------------------------------------------------------------

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),
  requestMagicLink: (email: string) =>
    request<{ message: string }>("/auth/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verifyMagicLink: (token: string) =>
    request<{ access_token: string; token_type: string }>("/auth/verify", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  setPassword: (password: string) =>
    request<{ ok: boolean }>("/auth/set-password", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  listScans: () => request<ScanSummary[]>("/scans"),
  getScan: (id: string) => request<ScanDetail>(`/scans/${id}`),
  getScanEvents: (id: string) => request<ScanEvent[]>(`/scans/${id}/events`),
  getScanFindings: (id: string) => request<Finding[]>(`/scans/${id}/findings`),
  getScanEvidence: (id: string) => request<EvidenceItem[]>(`/scans/${id}/evidence`),
  getScanReport: (id: string) => request<ReportOut>(`/scans/${id}/report`),
  deleteScan: (id: string) => request<void>(`/scans/${id}`, { method: "DELETE" }),
  createScan: (payload: {
    target_input: string;
    notes: string;
    max_pages: 10 | 25 | 50;
    authorization_acknowledgment: boolean;
  }) =>
    request<ScanDetail>("/scans", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export function exportHtmlUrl(scanId: string): string {
  return `${API_BASE}/scans/${scanId}/export/html`;
}
