"""Prometheus metrics for StarGate API."""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

http_requests_total = Counter(
    "stargate_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration = Histogram(
    "stargate_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
)

llm_calls_total = Counter(
    "stargate_llm_calls_total",
    "Total LLM calls",
    ["endpoint", "success"],
)

llm_call_duration = Histogram(
    "stargate_llm_call_duration_seconds",
    "LLM call duration",
    ["endpoint"],
    buckets=[0.5, 1, 2.5, 5, 10, 30, 60, 90],
)

llm_tokens_total = Counter(
    "stargate_llm_tokens_total",
    "Total LLM tokens consumed",
    ["endpoint", "type"],
)

cache_operations = Counter(
    "stargate_cache_operations_total",
    "Cache hits and misses",
    ["cache", "result"],
)

mv_refresh_duration = Gauge(
    "stargate_mv_refresh_duration_seconds",
    "Last MV refresh duration",
)

scanner_clusters_healthy = Gauge(
    "stargate_scanner_clusters_healthy",
    "Number of healthy clusters from last scan",
)
