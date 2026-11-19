#!/usr/bin/env python3
"""Measure CareQueue health, sampled availability, latency, and outage TTR."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("MONITORING_RESULTS_PATH", ROOT / "monitoring" / "results"))


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def percentile95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 2)


def check(url: str, timeout: float) -> tuple[bool, float | None, str]:
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "CareQueue-SLA-Monitor/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            elapsed_ms = (time.monotonic() - started) * 1000
            healthy = 200 <= response.status < 400
            return healthy, elapsed_ms, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        elapsed_ms = (time.monotonic() - started) * 1000
        return False, elapsed_ms, f"HTTP {error.code}"
    except Exception as error:  # network and timeout errors are recorded as failed checks
        elapsed_ms = (time.monotonic() - started) * 1000
        return False, elapsed_ms, type(error).__name__


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000/health", help="Health endpoint to check")
    parser.add_argument("--interval", type=float, default=5, help="Seconds between checks (default: 5)")
    parser.add_argument("--duration-minutes", type=float, default=10, help="Run length (default: 10 minutes)")
    parser.add_argument("--continuous", action="store_true", help="Keep checking and update the live summary after every poll")
    parser.add_argument("--timeout", type=float, default=3, help="Seconds to wait for each response (default: 3)")
    parser.add_argument("--availability-target", type=float, default=99.5, help="Target percentage")
    parser.add_argument("--p95-target-ms", type=float, default=2000, help="Target P95 latency in milliseconds")
    parser.add_argument("--ttr-target-seconds", type=float, default=120, help="Target TTR in seconds")
    args = parser.parse_args()

    if args.interval <= 0 or args.duration_minutes <= 0 or args.timeout <= 0:
        parser.error("interval, duration, and timeout must be greater than zero")

    RESULTS.mkdir(parents=True, exist_ok=True)
    run_id = "live" if args.continuous else datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = RESULTS / f"checks-{run_id}.csv"
    json_path = RESULTS / f"summary-{run_id}.json"
    started_at_utc = timestamp()
    deadline = float("inf") if args.continuous else time.monotonic() + args.duration_minutes * 60
    total_checks = 0
    successful_checks = 0
    successful_latencies: list[float] = []
    outages: list[dict] = []
    current_outage: dict | None = None
    consecutive_recovery_checks = 0

    if args.continuous:
        print(f"Monitoring {args.url} every {args.interval:g}s until stopped.")
    else:
        print(f"Monitoring {args.url} every {args.interval:g}s for {args.duration_minutes:g} minutes.")
        print("Press Ctrl+C to stop early and save the measurements.")

    def save_summary() -> None:
        availability = (successful_checks / total_checks * 100) if total_checks else 0.0
        p95 = percentile95(successful_latencies)
        recovered_ttrs = [event["ttr_seconds"] for event in outages if event["ttr_seconds"] is not None]
        summary = {
            "url": args.url,
            "started_at_utc": started_at_utc,
            "ended_at_utc": timestamp(),
            "poll_interval_seconds": args.interval,
            "checks_total": total_checks,
            "checks_successful": successful_checks,
            "sampled_availability_percent": round(availability, 3),
            "successful_check_p95_latency_ms": p95,
            "outages": outages,
            "recovered_outages": len(recovered_ttrs),
            "average_ttr_seconds": round(sum(recovered_ttrs) / len(recovered_ttrs), 2) if recovered_ttrs else None,
            "targets": {
                "availability_percent": args.availability_target,
                "p95_latency_ms": args.p95_target_ms,
                "ttr_seconds": args.ttr_target_seconds,
            },
            "target_results": {
                "availability_met": availability >= args.availability_target,
                "p95_latency_met": p95 is not None and p95 < args.p95_target_ms,
                "ttr_met_for_all_recovered_outages": bool(recovered_ttrs) and all(value <= args.ttr_target_seconds for value in recovered_ttrs),
            },
            "notes": [
                "Availability is sampled from this run only; it is not a monthly SLA measurement.",
                "TTR starts at the first failed poll and ends after two consecutive healthy polls.",
                "The monitor runs in a separate container so it can observe the app container restarting.",
            ],
        }
        json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["timestamp_utc", "healthy", "latency_ms", "result"])
        writer.writeheader()
        try:
            while args.continuous or time.monotonic() < deadline:
                checked_at = timestamp()
                healthy, latency_ms, result = check(args.url, args.timeout)
                total_checks += 1
                if healthy:
                    successful_checks += 1
                    successful_latencies.append(latency_ms or 0)
                writer.writerow({
                    "timestamp_utc": checked_at,
                    "healthy": str(healthy).lower(),
                    "latency_ms": "" if latency_ms is None else round(latency_ms, 2),
                    "result": result,
                })
                stream.flush()

                if not healthy:
                    if current_outage is None:
                        current_outage = {"detected_at_utc": checked_at, "recovered_at_utc": None, "ttr_seconds": None}
                        outages.append(current_outage)
                        print(f"{checked_at}  DOWN  {result}")
                    consecutive_recovery_checks = 0
                else:
                    print(f"{checked_at}  UP    {latency_ms:.1f} ms")
                    if current_outage is not None:
                        consecutive_recovery_checks += 1
                        if consecutive_recovery_checks >= 2:
                            recovered_at = datetime.fromisoformat(checked_at)
                            detected_at = datetime.fromisoformat(current_outage["detected_at_utc"])
                            current_outage["recovered_at_utc"] = checked_at
                            current_outage["ttr_seconds"] = round((recovered_at - detected_at).total_seconds(), 2)
                            print(f"RECOVERED  TTR {current_outage['ttr_seconds']:.1f}s (two consecutive healthy checks)")
                            current_outage = None
                            consecutive_recovery_checks = 0

                if args.continuous:
                    save_summary()

                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(args.interval, remaining))
        except KeyboardInterrupt:
            print("\nMonitoring stopped early; saving the measurements collected so far.")

    save_summary()
    availability = (successful_checks / total_checks * 100) if total_checks else 0.0
    p95 = percentile95(successful_latencies)
    print(f"\nSampled availability: {availability:.3f}% ({successful_checks}/{total_checks})")
    print(f"Successful-check P95: {p95 if p95 is not None else 'n/a'} ms")
    print(f"Measurements: {csv_path}")
    print(f"Summary: {json_path}")


if __name__ == "__main__":
    main()
