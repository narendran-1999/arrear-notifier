const STATE_URL = "../state/state.json";

function formatDate(isoString) {
  if (!isoString) return "–";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function daysBetween(a, b) {
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.floor((b.getTime() - a.getTime()) / msPerDay);
}

async function loadState() {
  const monitoringEl = document.getElementById("status-monitoring");
  const lastRunEl = document.getElementById("status-last-run");
  const lastResultEl = document.getElementById("status-last-result");
  const lastErrorEl = document.getElementById("status-last-error");
  const annEmptyEl = document.getElementById("announcement-empty");
  const annCardEl = document.getElementById("announcement-card");
  const annTextEl = document.getElementById("announcement-text");
  const annDateEl = document.getElementById("announcement-date");
  const annLinkWrapperEl = document.getElementById("announcement-link-wrapper");
  const annPdfEl = document.getElementById("announcement-pdf");

  try {
    const response = await fetch(STATE_URL, {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    const monitoringEnabled = Boolean(data.monitoring_enabled);
    monitoringEl.textContent = monitoringEnabled ? "ON" : "OFF";
    monitoringEl.classList.toggle("status-value--muted", !monitoringEnabled);

    lastRunEl.textContent = data.last_run_time ? formatDate(data.last_run_time) : "Never";

    if (data.last_run_status === "success") {
      lastResultEl.textContent = "Success";
      lastResultEl.style.color = "#22c55e";
    } else if (data.last_run_status === "failure") {
      lastResultEl.textContent = "Failure";
      lastResultEl.style.color = "#f97316";
    } else {
      lastResultEl.textContent = "Unknown";
      lastResultEl.style.color = "";
    }

    if (data.last_error_message) {
      lastErrorEl.textContent = data.last_error_message;
      lastErrorEl.classList.remove("status-value--muted");
    } else {
      lastErrorEl.textContent = "None";
      lastErrorEl.classList.add("status-value--muted");
    }

    const ann = data.last_announcement;
    if (ann && ann.first_detected) {
      const firstDetected = new Date(ann.first_detected);
      const now = new Date();
      const age = daysBetween(firstDetected, now);

      if (!Number.isNaN(firstDetected.getTime()) && age <= 30) {
        annTextEl.textContent = ann.text || "";
        annDateEl.textContent = formatDate(ann.first_detected);

        if (ann.pdf_url) {
          annPdfEl.href = ann.pdf_url;
          annLinkWrapperEl.hidden = false;
        } else {
          annLinkWrapperEl.hidden = true;
        }

        annCardEl.hidden = false;
        annEmptyEl.hidden = true;
      } else {
        annCardEl.hidden = true;
        annEmptyEl.hidden = false;
      }
    } else {
      annCardEl.hidden = true;
      annEmptyEl.hidden = false;
    }
  } catch (error) {
    monitoringEl.textContent = "Unknown";
    monitoringEl.classList.add("status-value--muted");
    lastRunEl.textContent = "Unavailable";
    lastResultEl.textContent = "Error loading state";
    lastResultEl.style.color = "#f97316";
    lastErrorEl.textContent = String(error);
    lastErrorEl.classList.remove("status-value--muted");

    document.getElementById("announcement-card").hidden = true;
    document.getElementById("announcement-empty").hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", loadState);

