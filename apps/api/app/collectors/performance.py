"""Collector 7: performance adapter.

`PerformanceProvider` is the seam for adding paid/external performance APIs
later without touching the orchestrator. The local provider always runs and
never depends on external services; Google PageSpeed Insights is optional
and skipped gracefully when unconfigured.
"""

import abc
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.models.evidence import EvidenceItem
from app.models.observation import PerformanceObservation

logger = get_logger(__name__)


class PerformanceProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def collect(self, final_url: str, context: dict) -> dict:
        """Returns a dict of PerformanceObservation-shaped fields."""


class LocalPerformanceProvider(PerformanceProvider):
    name = "local"

    def collect(self, final_url: str, context: dict) -> dict:
        return {
            "provider": "local",
            "configured": True,
            "response_duration_ms": context.get("response_duration_ms"),
            "html_bytes": context.get("html_bytes"),
            "third_party_domain_count": context.get("third_party_domain_count"),
            "js_resource_count": context.get("js_resource_count"),
        }


class GooglePageSpeedProvider(PerformanceProvider):
    name = "google_pagespeed"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    # Google's hosted PageSpeed Insights API (runPagespeed) only supports these four
    # Lighthouse categories. Lighthouse's standalone CLI added an experimental
    # "Agentic Browsing" category in v13.3, but as of this API's current reference
    # docs (developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed)
    # that category is not yet exposed through the hosted API — only through local
    # Lighthouse runs. Revisit once Google rolls it into this endpoint.
    CATEGORIES = ["PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"]

    # Google's own guidance and real-world experience both show individual
    # runPagespeed calls can take 30-60+ seconds (more for a cold cache),
    # so a short timeout here silently drops one strategy — most visibly
    # desktop, whose analysis frequently runs longer than mobile's cached
    # default. One retry absorbs transient timeouts/5xxs without doubling
    # the worst case for every scan.
    REQUEST_TIMEOUT_SECONDS = 90
    MAX_ATTEMPTS = 2

    def collect(self, final_url: str, context: dict, strategy: str) -> dict:
        params = {
            "url": final_url,
            "key": self.api_key,
            "strategy": strategy,
            "category": self.CATEGORIES,
        }
        last_error: Exception | None = None
        data = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=self.REQUEST_TIMEOUT_SECONDS) as client:
                    resp = client.get(
                        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params
                    )
                    resp.raise_for_status()
                    data = resp.json()
                break
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "pagespeed_request_failed", strategy=strategy, attempt=attempt, error=str(exc)
                )
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(2)

        if data is None:
            return {"provider": "google_pagespeed", "configured": True, "error": str(last_error)}

        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})

        def score(cat_key: str) -> int | None:
            cat = categories.get(cat_key)
            if not cat or cat.get("score") is None:
                return None
            return round(cat["score"] * 100)

        def metric(audit_key: str) -> float | None:
            audit = audits.get(audit_key)
            if not audit:
                return None
            return audit.get("numericValue")

        return {
            "provider": "google_pagespeed",
            "configured": True,
            "lcp_ms": metric("largest-contentful-paint"),
            "cls": metric("cumulative-layout-shift"),
            "inp_ms": metric("interaction-to-next-paint"),
            "fcp_ms": metric("first-contentful-paint"),
            "ttfb_ms": metric("server-response-time"),
            "performance_score": score("performance"),
            "accessibility_score": score("accessibility"),
            "best_practices_score": score("best-practices"),
            "seo_score": score("seo"),
        }


def run_performance_checks(db, scan_request_id: uuid.UUID, final_url: str, context: dict) -> dict:
    settings = get_settings()
    local_provider = LocalPerformanceProvider()
    merged: dict = {k: v for k, v in local_provider.collect(final_url, context).items() if v is not None}

    pagespeed_configured = bool(settings.google_pagespeed_api_key)
    provider_names = [local_provider.name]

    if pagespeed_configured:
        pagespeed_provider = GooglePageSpeedProvider(settings.google_pagespeed_api_key)
        provider_names.append(pagespeed_provider.name)
        for strategy in ("desktop", "mobile"):
            strategy_data = pagespeed_provider.collect(final_url, context, strategy)
            for key, value in strategy_data.items():
                if key in ("provider", "configured") or value is None:
                    continue
                merged[f"{strategy}_{key}"] = value

    observation = PerformanceObservation(
        scan_request_id=scan_request_id,
        provider="+".join(provider_names),
        configured=pagespeed_configured,
        response_duration_ms=merged.get("response_duration_ms"),
        html_bytes=merged.get("html_bytes"),
        third_party_domain_count=merged.get("third_party_domain_count"),
        js_resource_count=merged.get("js_resource_count"),
        desktop_lcp_ms=merged.get("desktop_lcp_ms"),
        desktop_cls=merged.get("desktop_cls"),
        desktop_inp_ms=merged.get("desktop_inp_ms"),
        desktop_fcp_ms=merged.get("desktop_fcp_ms"),
        desktop_ttfb_ms=merged.get("desktop_ttfb_ms"),
        desktop_performance_score=merged.get("desktop_performance_score"),
        desktop_accessibility_score=merged.get("desktop_accessibility_score"),
        desktop_best_practices_score=merged.get("desktop_best_practices_score"),
        desktop_seo_score=merged.get("desktop_seo_score"),
        mobile_lcp_ms=merged.get("mobile_lcp_ms"),
        mobile_cls=merged.get("mobile_cls"),
        mobile_inp_ms=merged.get("mobile_inp_ms"),
        mobile_fcp_ms=merged.get("mobile_fcp_ms"),
        mobile_ttfb_ms=merged.get("mobile_ttfb_ms"),
        mobile_performance_score=merged.get("mobile_performance_score"),
        mobile_accessibility_score=merged.get("mobile_accessibility_score"),
        mobile_best_practices_score=merged.get("mobile_best_practices_score"),
        mobile_seo_score=merged.get("mobile_seo_score"),
    )
    db.add(observation)
    db.flush()

    summary = (
        "Local performance measurements recorded. "
        + (
            f"Google PageSpeed Insights performance score — desktop: {merged.get('desktop_performance_score')}, "
            f"mobile: {merged.get('mobile_performance_score')}."
            if pagespeed_configured
            else "Google PageSpeed Insights was not configured for this scan; only local measurements are available."
        )
    )

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="performance",
        source_type="performance_measurement",
        source_url_or_identifier=final_url,
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json=merged,
        human_readable_summary=summary,
        raw_response_reference=None,
    )
    db.add(evidence)
    db.flush()

    merged["performance_configured"] = pagespeed_configured
    return merged
