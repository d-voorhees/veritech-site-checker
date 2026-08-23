import type {
  CONFIDENCE_LEVELS,
  EVIDENCE_CATEGORIES,
  SCAN_STATUSES,
  SEVERITY_LEVELS,
} from "./constants";

export type Severity = (typeof SEVERITY_LEVELS)[number];
export type Confidence = (typeof CONFIDENCE_LEVELS)[number];
export type ScanStatus = (typeof SCAN_STATUSES)[number];
export type EvidenceCategory = (typeof EVIDENCE_CATEGORIES)[number];
export type MaxPages = 10 | 25 | 50;
