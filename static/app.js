const $ = (selector) => document.querySelector(selector);
const statusLabels = {
  Waiting: "Waiting",
  "In consultation": "In progress",
  Completed: "Completed",
  Cancelled: "Cancelled",
};
let selectedFilter = "All";
let appointmentCache = [];
let toastTimer;
let editingAppointmentId = null;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatRunTime(value) {
  return value ? new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
}

function resultBadge(element, state, goodText = "On target", badText = "Below target") {
  element.classList.remove("good", "bad", "neutral");
  if (state === true) {
    element.textContent = goodText;
    element.classList.add("good");
  } else if (state === false) {
    element.textContent = badText;
    element.classList.add("bad");
  } else {
    element.textContent = "Not measured";
    element.classList.add("neutral");
  }
}

function clinicDay() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() || "").join("");
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 401) { window.location.href = "/login"; throw new Error("Signed out."); }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "Something went wrong. Please try again.");
  }
  return response.status === 204 ? null : response.json();
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

function renderRows(rows) {
  const body = $("#appointment-rows");
  $("#empty-state").classList.toggle("hidden", rows.length > 0);
  body.innerHTML = rows.map((appointment, index) => `
    <tr>
      <td><div class="patient-cell"><img class="patient-avatar" src="/static/img/patient-${(appointment.id || index) % 5}.svg" alt="" width="34" height="34"><div><b>${escapeHtml(appointment.patient_name)}</b><small>Appointment #${String(appointment.id).padStart(4, "0")}</small></div></div></td>
      <td class="time-cell">${formatTime(appointment.appointment_time)}</td>
      <td><span class="visit-type">${escapeHtml(appointment.visit_type)}</span></td>
      <td><select class="status-select status-${appointment.status.toLowerCase().replaceAll(" ", "-")}" data-status-id="${appointment.id}" aria-label="Change status for ${escapeHtml(appointment.patient_name)}">${Object.entries(statusLabels).map(([value, label]) => `<option value="${value}" ${appointment.status === value ? "selected" : ""}>${label}</option>`).join("")}</select></td>
      <td><div class="row-actions"><button class="row-action" title="Edit appointment" aria-label="Edit ${escapeHtml(appointment.patient_name)}" data-edit-id="${appointment.id}">✎</button><button class="row-action delete-action" title="Delete appointment" aria-label="Delete ${escapeHtml(appointment.patient_name)}" data-delete-id="${appointment.id}">×</button></div></td>
    </tr>`).join("");
  $("#table-count").textContent = `Showing ${rows.length} appointment${rows.length === 1 ? "" : "s"}`;
  $("#count-all").textContent = appointmentCache.length;
}

function renderQueue(appointments) {
  const waiting = appointments.filter((a) => a.status === "Waiting");
  $("#queue-count").textContent = waiting.length;
  $("#queue-empty").classList.toggle("hidden", waiting.length > 0);
  $("#queue-list").innerHTML = waiting.slice(0, 5).map((person, index) => `
    <div class="queue-person">
      <span class="queue-position">${String(index + 1).padStart(2, "0")}</span>
      <img class="patient-avatar" src="/static/img/patient-${(person.id || index) % 5}.svg" alt="" width="34" height="34">
      <div class="queue-person-info"><b>${escapeHtml(person.patient_name)}</b><small>${escapeHtml(person.visit_type)}</small></div>
      <span class="queue-time">${formatTime(person.appointment_time)}</span>
    </div>`).join("");
}

async function refresh() {
  const [appointments, summary] = await Promise.all([
    api(`/api/appointments?day=${clinicDay()}`),
    api(`/api/summary?day=${clinicDay()}`),
  ]);
  appointmentCache = appointments;
  $("#stat-total").textContent = summary.total;
  $("#stat-waiting").textContent = summary.waiting;
  $("#stat-consult").textContent = summary.in_consultation;
  $("#stat-completed").textContent = summary.completed;
  renderQueue(appointments);
  applyFilters();
  $("#system-status").textContent = "System operational";
  $(".health-led").classList.add("online");
  await refreshReliability().catch(() => {});
  await refreshOps().catch(() => {});
}

async function refreshReliability() {
  const data = await api("/api/monitoring");
  const report = data.latest;
  const empty = !report;
  $("#run-empty").classList.toggle("hidden", !empty);
  $("#run-details").classList.toggle("hidden", empty);
  $("#run-badge").textContent = empty ? "Awaiting data" : "Latest run";
  $("#run-period").textContent = empty ? "No monitoring run loaded yet." : `${formatRunTime(report.started_at_utc)} – ${formatRunTime(report.ended_at_utc)}`;

  if (report) {
    const availability = Number(report.sampled_availability_percent);
    const latency = report.successful_check_p95_latency_ms;
    const ttr = report.average_ttr_seconds;
    const targets = report.targets || {};
    const results = report.target_results || {};
    $("#reliability-availability").textContent = `${availability.toFixed(2)}%`;
    $("#target-availability").textContent = `${Number(targets.availability_percent ?? 99.5).toFixed(1)}%`;
    $("#availability-progress").style.width = `${Math.max(0, Math.min(100, availability))}%`;
    resultBadge($("#availability-result"), results.availability_met);

    $("#reliability-latency").textContent = latency == null ? "—" : Math.round(latency).toLocaleString();
    $("#target-latency").textContent = `${Number(targets.p95_latency_ms ?? 2000).toLocaleString()} ms`;
    resultBadge($("#latency-result"), results.p95_latency_met);

    $("#reliability-ttr").textContent = ttr == null ? "—" : Number(ttr).toFixed(1);
    $("#target-ttr").textContent = `${Number(targets.ttr_seconds ?? 120)} sec`;
    resultBadge($("#ttr-result"), ttr == null ? null : results.ttr_met_for_all_recovered_outages, "Recovered", "Over target");
    $("#ttr-caption").textContent = ttr == null ? "No recovered outage was recorded in this run." : `${report.recovered_outages} recovered outage${report.recovered_outages === 1 ? "" : "s"} measured in this run.`;

    $("#run-details").innerHTML = `
      <div class="run-detail"><span>Health checks</span><b>${Number(report.checks_total).toLocaleString()}</b></div>
      <div class="run-detail"><span>Successful</span><b>${Number(report.checks_successful).toLocaleString()} <small>(${availability.toFixed(2)}%)</small></b></div>
      <div class="run-detail"><span>Poll interval</span><b>${Number(report.poll_interval_seconds)} sec</b></div>`;
    const targetStates = [results.availability_met, results.p95_latency_met, ttr == null ? null : results.ttr_met_for_all_recovered_outages];
    $("#run-badge").textContent = targetStates.every((state) => state === true) ? "Targets met" : "Results recorded";
    $("#run-badge").classList.toggle("on-target", targetStates.every((state) => state === true));
  } else {
    $("#reliability-availability").textContent = "—";
    $("#reliability-latency").textContent = "—";
    $("#reliability-ttr").textContent = "—";
    $("#availability-progress").style.width = "0%";
    $("#ttr-caption").textContent = "Trigger a controlled restart to measure TTR.";
    resultBadge($("#availability-result"), null);
    resultBadge($("#latency-result"), null);
    resultBadge($("#ttr-result"), null, "Recovered", "Over target");
    $("#run-badge").classList.remove("on-target");
  }

  const incidents = (data.reports || []).flatMap((item) => (item.outages || []).map((event) => ({ ...event, runEndedAt: item.ended_at_utc })))
    .sort((a, b) => new Date(b.detected_at_utc) - new Date(a.detected_at_utc));
  $("#incident-total").textContent = incidents.length;
  $("#incident-list").innerHTML = incidents.length ? incidents.slice(0, 5).map((event) => `
    <div class="incident-item">
      <span class="incident-mark ${event.recovered_at_utc ? "recovered" : "open"}">${event.recovered_at_utc ? "✓" : "!"}</span>
      <div class="incident-copy"><b>${event.recovered_at_utc ? "Service recovered" : "Outage still open"}</b><small>Detected ${formatRunTime(event.detected_at_utc)}${event.recovered_at_utc ? ` · recovered ${formatRunTime(event.recovered_at_utc)}` : ""}</small></div>
      <span class="incident-duration">${event.ttr_seconds == null ? "—" : `${Number(event.ttr_seconds).toFixed(1)}s`}</span>
    </div>`).join("") : `<div class="incident-empty"><span>✳</span><b>No outages recorded</b><p>Run a controlled failure demo to capture recovery time.</p></div>`;
}

function applyFilters() {
  const search = $("#search").value.trim().toLowerCase();
  const filtered = appointmentCache.filter((item) => {
    const matchesStatus = selectedFilter === "All" || item.status === selectedFilter;
    return matchesStatus && item.patient_name.toLowerCase().includes(search);
  });
  renderRows(filtered);
}

function openModal(appointment = null) {
  editingAppointmentId = appointment?.id ?? null;
  $("#modal-title").textContent = editingAppointmentId ? "Edit appointment" : "New appointment";
  $("#save-appointment").innerHTML = editingAppointmentId ? "Save changes <span>→</span>" : "Add appointment <span>→</span>";
  $("#modal-backdrop").classList.remove("hidden");
  const now = new Date();
  now.setMinutes(Math.ceil(now.getMinutes() / 15) * 15, 0, 0);
  const localTime = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("#appointment-time").value = appointment ? appointment.appointment_time.slice(0, 16) : localTime;
  $("#patient-name").value = appointment?.patient_name ?? "";
  $("#visit-type").value = appointment?.visit_type ?? "General checkup";
  $("#patient-name").focus();
}

function closeModal() {
  $("#modal-backdrop").classList.add("hidden");
  $("#appointment-form").reset();
  editingAppointmentId = null;
}

$("#today-label").textContent = new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric" }).format(new Date()).toUpperCase();
$("#open-modal").addEventListener("click", () => openModal());
$("#close-modal").addEventListener("click", closeModal);
$("#cancel-modal").addEventListener("click", closeModal);
$("#modal-backdrop").addEventListener("click", (event) => { if (event.target === $("#modal-backdrop")) closeModal(); });
$("#search").addEventListener("input", applyFilters);
$("#view-all").addEventListener("click", () => {
  selectedFilter = "All";
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.filter === "All"));
  $("#search").value = "";
  applyFilters();
});
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  selectedFilter = tab.dataset.filter;
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab));
  applyFilters();
}));

$("#appointment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#save-appointment");
  const wasEditing = editingAppointmentId !== null;
  button.disabled = true;
  try {
    const data = new FormData(event.currentTarget);
    await api(editingAppointmentId ? `/api/appointments/${editingAppointmentId}` : "/api/appointments", {
      method: editingAppointmentId ? "PATCH" : "POST",
      body: JSON.stringify({
        patient_name: data.get("patient_name"),
        appointment_time: data.get("appointment_time"),
        visit_type: data.get("visit_type"),
      }),
    });
    closeModal();
    await refresh();
    showToast(wasEditing ? "Appointment details updated." : "Appointment added to the clinic schedule.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#appointment-rows").addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-id]");
  if (editButton) {
    const appointment = appointmentCache.find((item) => item.id === Number(editButton.dataset.editId));
    if (appointment) openModal(appointment);
    return;
  }
  const deleteButton = event.target.closest("[data-delete-id]");
  if (!deleteButton) return;
  const appointment = appointmentCache.find((item) => item.id === Number(deleteButton.dataset.deleteId));
  if (!appointment || !window.confirm(`Delete ${appointment.patient_name}'s appointment?`)) return;
  try {
    await api(`/api/appointments/${appointment.id}`, { method: "DELETE" });
    await refresh();
    showToast("Appointment deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

$("#appointment-rows").addEventListener("change", async (event) => {
  const select = event.target.closest("[data-status-id]");
  if (!select) return;
  try {
    await api(`/api/appointments/${select.dataset.statusId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: select.value }),
    });
    await refresh();
    showToast(`Status updated to ${statusLabels[select.value].toLowerCase()}.`);
  } catch (error) {
    showToast(error.message, true);
  }
});

api("/health").then(refresh).catch(() => {
  $("#system-status").textContent = "Service unavailable";
  $(".health-led").classList.add("offline");
  showToast("The clinic service could not be reached.", true);
});

$("#copy-monitor-command").addEventListener("click", async () => {
  const command = "python3 scripts/monitor.py --duration-minutes 10 --interval 5";
  try {
    await navigator.clipboard.writeText(command);
    showToast("Monitor command copied. Run it from your project folder.");
  } catch {
    $("#monitor-command").classList.remove("hidden");
    showToast("Copy the command shown below the measurement card.");
  }
});

setInterval(() => {
  refresh().catch(() => {
    $("#system-status").textContent = "Service unavailable";
    $(".health-led").classList.remove("online");
    $(".health-led").classList.add("offline");
  });
}, 10000);

$("#logout-button").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" }).catch(() => {});
  window.location.href = "/login";
});

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${seconds % 60}s` : `${seconds}s`;
}

async function refreshOps() {
  const [sys, perf, activity] = await Promise.all([api("/api/system"), api("/api/performance"), api("/api/activity")]);
  const rows = [["Host / container", sys.hostname], ["Operating system", sys.os], ["Architecture", sys.architecture], ["vCPU", sys.vcpus], ["Memory", sys.memory_gb == null ? "—" : `${sys.memory_gb} GB`], ["Storage", `${sys.storage_gb} GB (${sys.storage_used_percent}% used)`], ["Python", sys.python], ["Uptime", formatUptime(sys.uptime_seconds)], ["Timezone", sys.timezone]];
  $("#system-info").innerHTML = rows.map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join("");
  const fmt = (v, unit = " ms") => (v == null ? "—" : `${v}${unit}`);
  $("#perf-grid").innerHTML = [["Average", fmt(perf.average_ms)], ["P95", fmt(perf.p95_ms)], ["P99", fmt(perf.p99_ms)], ["Throughput", `${perf.requests_per_second} req/s`], ["Requests", perf.requests]].map(([k, v]) => `<div class="perf-item"><small>${k}</small><b>${escapeHtml(v)}</b></div>`).join("");
  $("#activity-list").innerHTML = activity.length ? activity.map((e) => `<div class="activity-item"><span class="act-time">${escapeHtml(e.ts.slice(11, 19))}</span><span class="act-method">${escapeHtml(e.method)}</span><span class="act-path">${escapeHtml(e.path)}</span><span class="act-status ${e.status >= 400 ? "err" : "ok"}">${e.status}</span><span class="act-user">${escapeHtml(e.user)} · ${escapeHtml(e.ip)}</span></div>`).join("") : `<div class="incident-empty"><b>No activity yet</b><p>Add or change an appointment to see it here.</p></div>`;
}

$("#simulate-failure").addEventListener("click", async () => {
  if (!window.confirm("Crash the app container now? It will be unavailable for about 15 seconds while Docker restarts it.")) return;
  const button = $("#simulate-failure");
  button.disabled = true;
  try {
    const result = await api("/api/simulate-failure", { method: "POST", body: JSON.stringify({ confirm: true }) });
    showToast(`Container crashing. Expected recovery in about ${result.expected_recovery_seconds}s.`);
  } catch (error) { showToast(error.message, true); }
  setTimeout(() => { button.disabled = false; }, 40000);
});

const adminPanel = $("#admin-panel");
document.querySelector('a[href="#reliability"]').addEventListener("click", () => { adminPanel.open = true; });
if (location.hash === "#reliability") adminPanel.open = true;
