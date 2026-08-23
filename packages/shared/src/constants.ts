// Cross-cutting constants that must stay in sync with the backend contract
// defined in apps/api/app/schemas/scan.py and apps/api/app/models. Kept here
// as the single documented source of truth; see packages/shared/README.md
// for how this package is currently consumed.

export const AUTHORIZATION_ACKNOWLEDGMENT_TEXT =
  "I confirm that I own this domain or am authorized to analyze its publicly available content.";

export const MAX_PAGES_OPTIONS = [10, 25, 50] as const;

export const SEVERITY_LEVELS = ["info", "low", "medium", "high"] as const;

export const CONFIDENCE_LEVELS = ["low", "medium", "high"] as const;

export const SCAN_STATUSES = [
  "queued",
  "running",
  "completed",
  "completed_with_warnings",
  "failed",
] as const;

export const EVIDENCE_CATEGORIES = [
  "http",
  "robots_sitemap",
  "crawl",
  "dns",
  "email_posture",
  "browser_render",
  "technology",
  "performance",
] as const;

export const DEFAULT_PRODUCT_IDENTITY = {
  productName: "Veritech Scan",
  parentBrand: "Veritech Diligence",
  reportName: "Technical Acquisition Brief",
  marketingSiteUrl: "https://veritechdiligence.com",
} as const;
