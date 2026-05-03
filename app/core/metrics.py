"""Prometheus metrics — process-local registry + standard counters/histograms.

Exposed via :func:`app.api.health.metrics` (Bearer-token guarded). The
registry is module-local so tests can clear it without leaking into other
processes; the ``/metrics`` route serialises this registry, not the global
default.

Reference: BACKEND_BLUEPRINT.md §17 (background jobs counters), §21
(observability).
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

# Module-local registry. The default global registry is shared across
# every imported library (sentry, etc.), which leaks unrelated counters
# into ``/metrics``. A dedicated registry keeps the surface clean.
REGISTRY = CollectorRegistry(auto_describe=True)


HTTP_REQUESTS_TOTAL = Counter(
    "pharmacy_http_requests_total",
    "Total HTTP requests by route, method, and response status.",
    labelnames=("route", "method", "status"),
    registry=REGISTRY,
)


HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "pharmacy_http_request_duration_seconds",
    "HTTP request latency by route + method.",
    labelnames=("route", "method"),
    # Tuned for an API with mostly sub-200ms reads + a few sub-500ms writes.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)


WORKER_JOBS_TOTAL = Counter(
    "pharmacy_worker_jobs_total",
    "Total ARQ worker job runs by job name and outcome.",
    labelnames=("job", "status"),  # status: 'success' | 'failed' | 'skipped'
    registry=REGISTRY,
)


def reset_for_tests() -> None:
    """Clear the module registry — used by tests that assert on counter
    values to avoid cross-test contamination.

    Counter/Histogram instances are immutable; the lightweight workaround
    is to clear the underlying ``_metrics`` dict on each collector.
    """
    for collector in (HTTP_REQUESTS_TOTAL, HTTP_REQUEST_DURATION_SECONDS, WORKER_JOBS_TOTAL):
        # ``_metrics`` is the labelled-children dict; clearing it resets
        # all observed label combinations. Public API doesn't expose
        # this, but it's the documented pattern in prometheus_client tests.
        collector._metrics.clear()
