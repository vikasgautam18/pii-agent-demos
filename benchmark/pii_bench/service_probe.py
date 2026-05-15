"""HTTP service probe: pre-flight health check + raw ``requests.post``
timing to break out the "wire + service" component from the full
middleware overhead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: float | None
    status_code: int | None
    detail: str


def healthcheck(api_url: str, timeout: int = 5) -> ProbeResult:
    """Probe ``${api_url}/health`` first; fall back to a benign POST to
    ``/anonymize_unique`` if /health is not implemented."""
    health = api_url.rstrip("/") + "/health"
    t0 = time.perf_counter_ns()
    try:
        resp = requests.get(health, timeout=timeout)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        if resp.ok:
            return ProbeResult(True, elapsed_ms, resp.status_code, "ok (/health)")
    except requests.RequestException:
        pass

    # Fallback: try a no-PII anonymize_unique call.
    t0 = time.perf_counter_ns()
    try:
        resp = requests.post(
            api_url.rstrip("/") + "/anonymize_unique",
            json={"text": "ping", "allow_list": [], "entity_type_allow_list": []},
            timeout=timeout,
        )
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        if resp.ok:
            return ProbeResult(True, elapsed_ms, resp.status_code, "ok (/anonymize_unique probe)")
        return ProbeResult(
            False, elapsed_ms, resp.status_code,
            f"unexpected status {resp.status_code}: {resp.text[:200]}",
        )
    except requests.RequestException as exc:
        return ProbeResult(False, None, None, f"network error: {exc}")


def time_raw_call(
    session: requests.Session,
    api_url: str,
    payload: dict,
    timeout: int = 10,
    app_id: str = "",
) -> float:
    """Time a single raw POST to /anonymize_unique. Returns latency in ms.

    Used for the service-vs-middleware breakdown — by subtracting this
    from the per-anonymize wallclock inside the middleware we can isolate
    the Python-side overhead the middleware itself adds.
    """
    headers = {"Content-Type": "application/json"}
    if app_id:
        headers["X-App-Id"] = app_id
    url = api_url.rstrip("/") + "/anonymize_unique"
    t0 = time.perf_counter_ns()
    resp = session.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    _ = resp.json()
    return (time.perf_counter_ns() - t0) / 1e6
