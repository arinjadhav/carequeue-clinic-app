# CareQueue project results

All values below were measured against the local Docker prototype on the development laptop. They are not AWS or production results.

## Recovery exercise

- Method: stop the app container while the separate monitor continues, then start it again.
- TTR rule: first failed 5-second health poll through two consecutive successful polls.
- Recovered incidents: 1.
- Average TTR: 20.09 seconds (one recovered incident).
- Proposed recovery target: 120 seconds; met in this local exercise.

## Read-only API load run

- Request: `GET /api/appointments?day=2026-11-19`
- Requests: 200; concurrency: 10; successful: 200; failed: 0.
- Duration: 0.22 seconds; reported throughput: 910.92 requests/second.
- Latency: P50 6.70 ms; P95 33.33 ms; P99 63.26 ms; mean 10.83 ms.
- Proposed local P95 target: 2,000 ms; met in this small run.
- This brief local benchmark does not establish AWS capacity or real clinic workload performance.

## Sampled availability window

One monitor summary recorded 436 checks, 432 successful (99.083%) and 15.84 ms P95 successful `/health` latency. The summary includes one recovered outage and one outage still open when that monitoring process stopped. It is an incomplete local sample, not a valid calendar-month SLA result. Use the controlled recovery result and read-only benchmark as separate evidence; do not claim 99.083% as the achieved monthly SLA.

## Remaining AWS evidence

EC2 deployment, CloudWatch logs/metrics/canary, AWS availability window, AWS failure/recovery TTR, and an AWS-hosted demo URL remain unmeasured. See `AWS-DEPLOYMENT.md` for the plan. Never use real patient data in this prototype.
