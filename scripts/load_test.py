#!/usr/bin/env python3
"""Run a small read-only concurrent HTTP benchmark against CareQueue."""

from __future__ import annotations

import argparse
import json
import os
import math
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "monitoring" / "results"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(p * len(values)) - 1)], 2)


def request_once(url: str, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CareQueue-Classroom-Load-Test/1.0", **({"Cookie": os.environ["CAREQUEUE_COOKIE"]} if os.environ.get("CAREQUEUE_COOKIE") else {})})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response.read()
            return {"ok": 200 <= response.status < 400, "status": response.status, "ms": (time.perf_counter() - started) * 1000}
    except urllib.error.HTTPError as error:
        return {"ok": False, "status": error.code, "ms": (time.perf_counter() - started) * 1000}
    except Exception as error:
        return {"ok": False, "status": type(error).__name__, "ms": (time.perf_counter() - started) * 1000}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000/api/appointments", help="Read-only API URL")
    parser.add_argument("--requests", type=int, default=200, help="Total requests (default: 200)")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers (default: 10)")
    parser.add_argument("--timeout", type=float, default=5, help="Per-request timeout in seconds")
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.timeout <= 0:
        parser.error("requests, concurrency, and timeout must be greater than zero")

    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request_once, args.url, args.timeout) for _ in range(args.requests)]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.perf_counter() - start

    latencies = [item["ms"] for item in results if item["ok"]]
    successes = len(latencies)
    summary = {
        "url": args.url,
        "started_at_utc": started_at.isoformat(timespec="seconds"),
        "requests_total": args.requests,
        "requests_successful": successes,
        "requests_failed": args.requests - successes,
        "concurrency": args.concurrency,
        "duration_seconds": round(elapsed, 3),
        "throughput_requests_per_second": round(args.requests / elapsed, 2),
        "successful_request_p50_ms": percentile(latencies, 0.50),
        "successful_request_p95_ms": percentile(latencies, 0.95),
        "successful_request_p99_ms": percentile(latencies, 0.99),
        "successful_request_mean_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "notes": [
            "Read-only local prototype benchmark; results are not AWS deployment performance.",
            "Use an explicit workload and test window when reporting results.",
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / f"load-test-{started_at.strftime('%Y%m%d-%H%M%S')}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved results to {output}")


if __name__ == "__main__":
    main()
