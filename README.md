# CareQueue clinic appointment prototype

A small clinic front-desk demo for the cloud mini-project. It supports creating and editing appointments, changing visit status, removing appointments, filtering the day’s schedule, and displaying the live waiting queue. It includes a `/health` endpoint for a simple availability check.

The **SLA & recovery** section in the app shows the latest availability / latency summary and incident history from a separate local monitor container. Compose starts both containers; the monitor checks the app every five seconds and the panel refreshes automatically. The app container receives the results folder as a read-only mount.

## Demo-data boundary

This is a classroom prototype, not a production healthcare system. Use fictional names and appointment details only. It has no login, role-based access control, encryption workflow, audit trail, backups, or production privacy controls. Do not enter real patient information.

## Run locally with Docker

After extracting the ZIP in Downloads:

```sh
cd ~/Downloads/clinic-queue-app
docker compose up --build
```

Open <http://localhost:8000>. The first launch seeds four fictional appointments for today. The named Docker volume keeps the SQLite demo database across container restarts. The container checks `/health` every ten seconds and uses a restart policy for unexpected exits.

To stop the demo:

```sh
docker compose down
```

To remove the demo database and reset the fictional appointments:

```sh
docker compose down -v
```

## Run without Docker

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The database is created at `data/clinic.db`.

## Routes

- `GET /health` — service health and timestamp
- `GET /api/appointments` — today’s appointments; supports `day`, `status`, and `search` query parameters
- `GET /api/summary` — counts by appointment status
- `POST /api/appointments` — add a fictional appointment
- `PATCH /api/appointments/{id}` — update its status
- `DELETE /api/appointments/{id}` — remove a demo appointment

## Mini-project status and evidence

The local prototype and measurements are ready for a classroom demo. See `AWS-DEPLOYMENT.md` for the proposed AWS design and deployment checklist. AWS resources have not been created.

Recorded evidence (all local; not AWS measurements):

- Controlled Docker recovery: TTR 20.09 seconds, against the proposed 120-second target.
- Read-only appointment API load run: 200/200 successes at concurrency 10; P95 33.33 ms and P99 63.26 ms.
- One sampled monitor window: 99.083% across 436 checks (432 successful); this short window is not a monthly SLA result.
- The monitor run also ended with an incomplete outage record, so do not present its aggregate availability as proof of the target. The controlled recovery result is reported separately.

## Local SLA / TTR measurement

Start the app and external monitor with `docker compose up --build -d`. Wait about 10 seconds, then open the app’s **SLA & recovery** section. The monitor writes a CSV and a live JSON summary under `monitoring/results/`; the dashboard reads the summary automatically.

For a controlled recovery demonstration, run this in a separate terminal while the app is open. This simulates an operator-detected service outage and manual container recovery:

```sh
docker compose stop clinic-queue
# Wait for the monitor to record a failed check (about 5-10 seconds)
docker compose start clinic-queue
```

The separate monitor keeps running. It records the first failed check as detection and confirms recovery after two healthy checks. The dashboard then shows the observed TTR and incident. This measures the local Docker demo; it is not CloudWatch evidence or a production SLA measurement.

To inspect the monitor’s live output, run `docker compose logs -f clinic-monitor`.

Optional target settings:

```sh
python3 scripts/monitor.py --duration-minutes 10 --interval 5 --availability-target 99.5 --p95-target-ms 2000 --ttr-target-seconds 120
```

Optional read-only appointment-list load run:

```sh
python3 scripts/load_test.py --url http://localhost:8000/api/appointments?day=2026-11-19 --requests 200 --concurrency 10
```

The accompanying project presentation lists the assignment checklist and remaining AWS evidence. This remains a classroom prototype; never enter real patient data.

## Security (v0.2)

- **Admin sign-in:** copy `.env.example` to `.env` and set `ADMIN_USERNAME`, `ADMIN_PASSWORD` and `SECRET_KEY` before `docker compose up --build`. If no password is set, a one-time password is generated and printed in `docker compose logs clinic-queue`.
- Signed, HttpOnly, SameSite=Strict session cookie (8 h); login rate-limited to 5 attempts per 5 minutes per IP; all `/api/*` routes require a session; only `/health` and the login page are public.
- Security headers (CSP, X-Frame-Options, nosniff, no-referrer), API docs disabled, `no-store` caching on data, input rejects `<` and `>` in names, container runs as non-root with `no-new-privileges` and all capabilities dropped.
- **Structured JSON request logs** (timestamp, IP, user, method, path, status, ms) go to stdout for CloudWatch; login failures are logged as warnings.
- Set `COOKIE_SECURE=1` once HTTPS is in front of the app (ALB/CloudFront). Not covered: HTTPS termination, password hashing in a user table, multi-user roles, encryption of the SQLite file at rest (use an encrypted EBS volume).
- `/auth/login` and `/auth/logout` are new routes. For the load test, sign in, copy the `cq_session` cookie and run `CAREQUEUE_COOKIE="cq_session=..." python3 scripts/load_test.py`.

## Operations panel (v0.3)

- **System info** (`GET /api/system`): host/container, OS, vCPU, memory, storage, uptime. Run it on EC2 for the VM-specification slide (note: inside Docker, vCPU and memory reflect the host VM).
- **Live performance** (`GET /api/performance`): average, P95, P99 and throughput over the last 5 minutes of app requests.
- **Activity log** (`GET /api/activity`): recent changes, sign-ins and errors.
- **Failure injection** (`POST /api/simulate-failure`): crashes the container; Docker's `restart: unless-stopped` brings it back after ~`CRASH_RECOVERY_DELAY` seconds (default 12, set in `.env`), and the external monitor records the TTR. Use on the demo only.

## Admin panel & `.env`

The reliability center, system info, live performance, activity log and failure injection now live in a collapsible **Admin panel** directly under the appointments (sidebar: *Admin panel*). A starter `.env` (admin / user123) is included for local demos only: change the password before deploying to AWS, and never commit `.env` (it is in `.gitignore` and `.dockerignore`).

- **One-command start:** `bash start.sh` builds and starts the app, prints the link and sign-in details, and opens the browser.
