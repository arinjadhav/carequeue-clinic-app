# CareQueue: Clinic Appointment Queue

A small clinic front-desk web app built as a **Cloud Computing mini project** (industry use case: healthcare). It manages appointments and the waiting room, and it includes the pieces needed to measure **SLA** and **TTR** on **AWS** with **Docker**.

> Prototype only. Use fictional patient data. Never enter real patient information.

## Features

- Add, edit, delete appointments; change status (Waiting, In progress, Completed, Cancelled)
- Live waiting room, search, filters and daily summary
- Admin sign-in with signed session cookie, login rate limiting and security headers
- Collapsible **Admin panel**: SLA and recovery dashboard, system info (vCPU, memory, storage), live performance (average, P95, P99), activity log, and a container-crash button for TTR demos
- Structured JSON request logs, ready for CloudWatch
- `/health` endpoint, container health check, and an external monitor container

**Stack:** Python 3.12, FastAPI, SQLite, vanilla JS/CSS, Docker Compose.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the Compose plugin)
- Git

## Install and run (Docker)

```bash
git clone https://github.com/arinjadhav/carequeue-clinic-app.git
cd carequeue-clinic-app
```

Create a `.env` file with your admin login (this file is never committed):

```bash
cat > .env <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=choose-a-long-passphrase
SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
COOKIE_SECURE=0
CRASH_RECOVERY_DELAY=12
EOF
```

Start the app:

```bash
bash start.sh
```

`start.sh` builds the containers, waits until the app responds, prints the link and sign-in details, and opens the browser. Or run it manually:

```bash
docker compose up --build -d
```

Then open **http://localhost:8000/login** and sign in with the username and password from your `.env`.

Useful commands:

```bash
docker compose ps                       # check containers
docker compose logs -f clinic-queue     # view app logs
docker compose down                     # stop (keeps data)
docker compose down -v                  # stop and delete the database
```

## Install without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADMIN_PASSWORD=choose-a-long-passphrase
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/login. The database is created at `data/clinic.db`. The SLA dashboard needs the monitor container, so it stays empty in this mode.

## Deploy on AWS (EC2 + Docker)

1. **Account:** create an AWS account, turn on MFA, and set a Budget alert. Use the Mumbai region (`ap-south-1`).
2. **IAM role:** create an EC2 role with `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`.
3. **Launch EC2:** Amazon Linux 2023, a *Free tier eligible* instance type, no key pair (use Session Manager), 20 GB encrypted gp3 storage, the IAM role above, and a security group with **one** inbound rule: TCP 8000 from **My IP**.
4. **Connect:** EC2, Connect, Session Manager. Install Docker and Compose:

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

5. **Deploy:**

```bash
git clone https://github.com/arinjadhav/carequeue-clinic-app.git
cd carequeue-clinic-app
cat > .env <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=use-a-strong-password-here
SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
COOKIE_SECURE=0
CRASH_RECOVERY_DELAY=12
EOF
sudo docker compose up --build -d
curl localhost:8000/health
```

6. **Open:** `http://<EC2-public-IPv4>:8000/login`
7. **Monitoring:** create a CloudWatch alarm on `StatusCheckFailed` for the instance.
8. **Clean up:** terminate the instance when finished, and check for leftover volumes and Elastic IPs.

## Measuring SLA and TTR

| Metric | Target (proposed) | Where to see it |
|---|---|---|
| Availability | 99.5% | Admin panel, Reliability center |
| Health-check P95 latency | under 2,000 ms | Admin panel, Reliability center |
| TTR | under 120 s | Admin panel, incident history |
| RTO / RPO | 2 min / 24 h | Admin panel, Failure injection |

**Controlled recovery test:** open the Admin panel and click **Simulate container crash** (or run `docker compose stop clinic-queue`, wait about 10 seconds, then `docker compose start clinic-queue`). The external monitor records detection and recovery, and the dashboard shows the measured TTR.

**Load test:** sign in, copy the `cq_session` cookie from your browser, then run:

```bash
CAREQUEUE_COOKIE="cq_session=..." python3 scripts/load_test.py
```

Results are saved to `monitoring/results/`.

## Security

- Signed HttpOnly, SameSite=Strict session cookie; login limited to 5 attempts per 5 minutes per IP
- All `/api/*` routes require sign-in; only `/health` and the login page are public
- CSP, X-Frame-Options, nosniff and no-referrer headers; API docs disabled
- Secrets in `.env` (git-ignored); container runs as non-root, drops all capabilities and blocks privilege escalation
- Not covered: HTTPS (use an Application Load Balancer with an ACM certificate and set `COOKIE_SECURE=1`), multi-user roles, password hashing in a user table

## Project structure

```
app/main.py          FastAPI app, auth, API routes, logging
static/              Frontend (index.html, login.html, app.js, styles.css, img/)
scripts/             monitor.py (external monitor), load_test.py
compose.yaml         App and monitor containers
Dockerfile           Python 3.12 slim image, non-root user
start.sh             One-command start
AWS-DEPLOYMENT.md    AWS design notes
PROJECT-RESULTS.md   Recorded measurements
```

## API routes

| Route | Purpose |
|---|---|
| `GET /health` | Health check (public) |
| `POST /auth/login`, `POST /auth/logout` | Sign in and out |
| `GET/POST /api/appointments` | List and create appointments |
| `PATCH/DELETE /api/appointments/{id}` | Update or delete an appointment |
| `GET /api/summary` | Counts by status |
| `GET /api/monitoring` | Latest monitor reports |
| `GET /api/system` | VM and container details |
| `GET /api/performance` | Latency and throughput (last 5 minutes) |
| `GET /api/activity` | Recent changes and sign-ins |
| `POST /api/simulate-failure` | Crash the container for a recovery demo |

<br>
