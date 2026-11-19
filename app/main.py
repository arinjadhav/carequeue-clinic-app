from __future__ import annotations

import os
import json
import time as clock
import hmac
import base64
import hashlib
import logging
import secrets
import math
import shutil
import asyncio
import platform
import threading
from collections import defaultdict, deque
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent
DATABASE = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "clinic.db"))
MONITORING_RESULTS = Path(os.environ.get("MONITORING_RESULTS_PATH", ROOT / "monitoring" / "results"))
APP_TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))
STATUSES = ("Waiting", "In consultation", "Completed", "Cancelled")
VISIT_TYPES = ("General checkup", "Follow-up", "Vaccination", "Dental", "Other")


def clinic_now() -> datetime:
    return datetime.now(APP_TIMEZONE)


def clinic_today() -> date:
    return clinic_now().date()


def connect() -> sqlite3.Connection:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                visit_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Waiting',
                created_at TEXT NOT NULL
            )"""
        )
        count = db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
        if count == 0:
            today = clinic_today()
            samples = [
                ("Demo patient 01", time(9, 0), "General checkup", "Waiting"),
                ("Demo patient 02", time(9, 30), "Follow-up", "In consultation"),
                ("Demo patient 03", time(10, 0), "Vaccination", "Waiting"),
                ("Demo patient 04", time(10, 30), "Dental", "Completed"),
            ]
            for name, slot, visit_type, status in samples:
                db.execute(
                    "INSERT INTO appointments (patient_name, appointment_time, visit_type, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, datetime.combine(today, slot).isoformat(timespec="minutes"), visit_type, status, clinic_now().isoformat(timespec="seconds")),
                )


@asynccontextmanager
async def lifespan(_: FastAPI):
    flag = DATABASE.parent / ".simulated-crash"
    if flag.exists():
        flag.unlink(missing_ok=True)
        await asyncio.sleep(CRASH_DELAY)
    initialize_database()
    yield


app = FastAPI(title="Clinic Queue", version="0.2.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


# ---------------------------------------------------------------- security & logging
logger = logging.getLogger("carequeue")
logging.basicConfig(level=logging.INFO, format="%(message)s")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
SECRET_KEY = (os.environ.get("SECRET_KEY") or secrets.token_hex(32)).encode()
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
SESSION_SECONDS = int(os.environ.get("SESSION_HOURS", "8")) * 3600
COOKIE_NAME = "cq_session"
if not os.environ.get("ADMIN_PASSWORD"):
    logger.warning(json.dumps({"event": "no_admin_password_set", "note": "Generated a one-time password; set ADMIN_PASSWORD in .env", "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}))

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
login_attempts: dict[str, deque] = defaultdict(deque)
STARTED_AT = clock.time()
CRASH_DELAY = int(os.environ.get("CRASH_RECOVERY_DELAY", "12"))
LATENCIES: deque = deque(maxlen=2000)
ACTIVITY: deque = deque(maxlen=100)
OPS_PATHS = {"/api/system", "/api/performance", "/api/activity", "/api/monitoring"}


def sign(value: str) -> str:
    return hmac.new(SECRET_KEY, value.encode(), hashlib.sha256).hexdigest()


def make_session(username: str) -> str:
    payload = base64.urlsafe_b64encode(f"{username}|{int(clock.time()) + SESSION_SECONDS}".encode()).decode()
    return f"{payload}.{sign(payload)}"


def session_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME, "")
    payload, _, signature = token.partition(".")
    if not payload or not hmac.compare_digest(signature, sign(payload)):
        return None
    try:
        username, expires = base64.urlsafe_b64decode(payload.encode()).decode().split("|")
        return username if int(expires) > clock.time() else None
    except ValueError:
        return None


@app.middleware("http")
async def guard_and_log(request: Request, call_next):
    started = clock.perf_counter()
    path = request.url.path
    user = session_user(request)
    if path.startswith("/api/") and not user:
        response = JSONResponse({"detail": "Please sign in to continue."}, status_code=401)
    elif path == "/" and not user:
        response = RedirectResponse("/login", status_code=303)
    else:
        response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    if path.startswith("/api/") or path == "/":
        response.headers["Cache-Control"] = "no-store"
    elapsed_ms = round((clock.perf_counter() - started) * 1000, 1)
    if path.startswith("/api/") and path not in OPS_PATHS:
        LATENCIES.append((clock.time(), elapsed_ms))
    if path != "/health":
        entry = {"ts": clinic_now().isoformat(timespec="seconds"), "ip": request.client.host if request.client else "-", "user": user or "-", "method": request.method, "path": path, "status": response.status_code, "ms": elapsed_ms}
        if path not in OPS_PATHS and (request.method != "GET" or response.status_code >= 400):
            ACTIVITY.append(entry)
        logger.info(json.dumps(entry))
    return response


class LoginPayload(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if session_user(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(ROOT / "static" / "login.html")


@app.post("/auth/login")
def login(payload: LoginPayload, request: Request):
    ip = request.client.host if request.client else "-"
    attempts = login_attempts[ip]
    while attempts and attempts[0] < clock.time() - 300:
        attempts.popleft()
    if len(attempts) >= 5:
        logger.warning(json.dumps({"event": "login_rate_limited", "ip": ip}))
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    ok = hmac.compare_digest(payload.username.encode(), ADMIN_USERNAME.encode()) & hmac.compare_digest(payload.password.encode(), ADMIN_PASSWORD.encode())
    if not ok:
        attempts.append(clock.time())
        logger.warning(json.dumps({"event": "login_failed", "ip": ip}))
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    attempts.clear()
    response = JSONResponse({"ok": True, "username": ADMIN_USERNAME})
    response.set_cookie(COOKIE_NAME, make_session(ADMIN_USERNAME), max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=COOKIE_SECURE, path="/")
    return response


@app.post("/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


class AppointmentCreate(BaseModel):
    patient_name: str = Field(min_length=2, max_length=80, pattern=r"^[^<>]*$")
    appointment_time: datetime
    visit_type: Literal["General checkup", "Follow-up", "Vaccination", "Dental", "Other"]


class AppointmentUpdate(BaseModel):
    patient_name: str | None = Field(default=None, min_length=2, max_length=80)
    appointment_time: datetime | None = None
    visit_type: Literal["General checkup", "Follow-up", "Vaccination", "Dental", "Other"] | None = None
    status: Literal["Waiting", "In consultation", "Completed", "Cancelled"] | None = None


def appointment_dict(row: sqlite3.Row) -> dict:
    return dict(row)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ROOT / "static" / "index.html")


class FailureRequest(BaseModel):
    confirm: bool


@app.get("/api/system")
def system_info():
    memory_gb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal"):
                    memory_gb = round(int(line.split()[1]) / 1048576, 2)
                    break
    except OSError:
        pass
    disk = shutil.disk_usage(DATABASE.parent if DATABASE.parent.exists() else ROOT)
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "vcpus": os.cpu_count(),
        "memory_gb": memory_gb,
        "storage_gb": round(disk.total / 1e9, 1),
        "storage_used_percent": round(disk.used / disk.total * 100, 1),
        "python": platform.python_version(),
        "uptime_seconds": int(clock.time() - STARTED_AT),
        "timezone": str(APP_TIMEZONE),
    }


@app.get("/api/performance")
def performance():
    now = clock.time()
    samples = [(t, ms) for t, ms in LATENCIES if t >= now - 300]
    values = sorted(ms for _, ms in samples)

    def pct(p: float):
        return round(values[max(0, math.ceil(p * len(values)) - 1)], 1) if values else None

    span = max(now - samples[0][0], 1) if samples else 1
    return {"window_seconds": 300, "requests": len(values), "average_ms": round(sum(values) / len(values), 1) if values else None, "p95_ms": pct(0.95), "p99_ms": pct(0.99), "requests_per_second": round(len(values) / span, 2) if values else 0}


@app.get("/api/activity")
def activity():
    return list(ACTIVITY)[-12:][::-1]


@app.post("/api/simulate-failure")
def simulate_failure(payload: FailureRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required.")
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    (DATABASE.parent / ".simulated-crash").write_text("1", encoding="utf-8")
    logger.warning(json.dumps({"event": "simulated_container_crash", "expected_recovery_seconds": CRASH_DELAY}))
    threading.Timer(0.5, os._exit, [1]).start()
    return {"status": "crashing", "expected_recovery_seconds": CRASH_DELAY}


@app.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "timestamp": clinic_now().isoformat(timespec="seconds")}


@app.get("/api/appointments")
def list_appointments(
    day: date | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str = Query(default="", max_length=80),
):
    selected_day = day or clinic_today()
    clauses = ["date(appointment_time) = ?"]
    values: list[str] = [selected_day.isoformat()]
    if status in STATUSES:
        clauses.append("status = ?")
        values.append(status)
    if search.strip():
        clauses.append("patient_name LIKE ?")
        values.append(f"%{search.strip()}%")
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM appointments WHERE {' AND '.join(clauses)} ORDER BY appointment_time, id",
            values,
        ).fetchall()
    return [appointment_dict(row) for row in rows]


@app.get("/api/summary")
def summary(day: date | None = Query(default=None)):
    selected_day = (day or clinic_today()).isoformat()
    with connect() as db:
        rows = db.execute(
            "SELECT status, COUNT(*) AS total FROM appointments WHERE date(appointment_time) = ? GROUP BY status",
            (selected_day,),
        ).fetchall()
    totals = {row["status"]: row["total"] for row in rows}
    return {
        "total": sum(totals.values()),
        "waiting": totals.get("Waiting", 0),
        "in_consultation": totals.get("In consultation", 0),
        "completed": totals.get("Completed", 0),
    }


@app.get("/api/monitoring")
def monitoring():
    reports = []
    if MONITORING_RESULTS.exists():
        for report_path in sorted(MONITORING_RESULTS.glob("summary-*.json"), reverse=True)[:10]:
            try:
                reports.append(json.loads(report_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return {"reports": reports, "latest": reports[0] if reports else None}


@app.post("/api/appointments", status_code=201)
def create_appointment(payload: AppointmentCreate):
    if payload.appointment_time.date() < clinic_today():
        raise HTTPException(status_code=400, detail="Choose today or a future date.")
    created_at = clinic_now().isoformat(timespec="seconds")
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO appointments (patient_name, appointment_time, visit_type, status, created_at) VALUES (?, ?, ?, 'Waiting', ?)",
            (payload.patient_name.strip(), payload.appointment_time.isoformat(timespec="minutes"), payload.visit_type, created_at),
        )
        row = db.execute("SELECT * FROM appointments WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return appointment_dict(row)


@app.patch("/api/appointments/{appointment_id}")
def update_appointment(appointment_id: int, payload: AppointmentUpdate):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")
    if "patient_name" in changes:
        changes["patient_name"] = changes["patient_name"].strip()
    if "appointment_time" in changes:
        if changes["appointment_time"].date() < clinic_today():
            raise HTTPException(status_code=400, detail="Choose today or a future date.")
        changes["appointment_time"] = changes["appointment_time"].isoformat(timespec="minutes")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    with connect() as db:
        cursor = db.execute(
            f"UPDATE appointments SET {assignments} WHERE id = ?",
            [*changes.values(), appointment_id],
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        row = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    return appointment_dict(row)


@app.delete("/api/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: int):
    with connect() as db:
        cursor = db.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Appointment not found.")
    return None
