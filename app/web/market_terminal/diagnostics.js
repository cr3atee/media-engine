/** Safe browser reporting and product-admin incident journal. */
const pageSize = 20;
const reportCooldownMs = 30_000;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

export function installFrontendDiagnostics({ send, isAuthenticated }) {
  const reportedAt = new Map();
  let sending = false;

  function report(kind, component, action) {
    if (!isAuthenticated() || sending) return;
    const key = `${kind}:${component}:${action}`;
    const now = Date.now();
    if (now - (reportedAt.get(key) || 0) < reportCooldownMs) return;
    reportedAt.set(key, now);
    sending = true;
    void send({
      kind,
      page: "review",
      component,
      action,
      request_id: "unavailable",
    }).catch(() => {}).finally(() => { sending = false; });
  }

  window.addEventListener("error", event => {
    if (event instanceof ErrorEvent && event.error?.name !== "ApiRequestError") {
      report("error", "shell", "render");
    }
  });
  window.addEventListener("unhandledrejection", event => {
    if (event.reason?.name !== "ApiRequestError") {
      report("unhandled_rejection", "shell", "render");
    }
  });

  return {
    reportRequestFailure: () => report("request_failure", "network", "load"),
  };
}

export function createDiagnosticJournal({ request, onSessionLost }) {
  const ids = [
    "diagnosticJournal", "diagnosticsLink", "diagnosticsClose",
    "diagnosticsTitle", "diagnosticsFilters", "diagnosticsSeverity",
    "diagnosticsSource", "diagnosticsComponent", "diagnosticsMessage",
    "diagnosticsList", "diagnosticsPagination", "diagnosticsPrevious",
    "diagnosticsNext", "diagnosticsRange",
  ];
  const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
  let profile = null;
  let offset = 0;
  let total = 0;
  let busy = false;
  let epoch = 0;

  function setProfile(user) {
    profile = user;
    const allowed = user?.product_role === "admin";
    el.diagnosticsLink.hidden = !allowed;
    if (!allowed) reset();
  }

  function reset() {
    epoch += 1;
    offset = 0;
    total = 0;
    busy = false;
    el.diagnosticJournal.hidden = true;
    el.diagnosticsList.replaceChildren();
    el.diagnosticsPagination.hidden = true;
    message("");
  }

  function message(text, error = false) {
    el.diagnosticsMessage.textContent = text;
    el.diagnosticsMessage.classList.toggle("error", error);
  }

  async function open() {
    if (profile?.product_role !== "admin") return;
    el.diagnosticJournal.hidden = false;
    el.diagnosticsTitle.focus();
    el.diagnosticJournal.scrollIntoView({
      block: "start",
      behavior: reducedMotion.matches ? "auto" : "smooth",
    });
    await load();
  }

  async function load() {
    if (busy || profile?.product_role !== "admin") return;
    const current = ++epoch;
    busy = true;
    controls();
    message("Загружаем журнал…");
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
    if (el.diagnosticsSeverity.value) query.set("severity", el.diagnosticsSeverity.value);
    if (el.diagnosticsSource.value) query.set("source", el.diagnosticsSource.value);
    if (el.diagnosticsComponent.value.trim()) query.set("component", el.diagnosticsComponent.value.trim());
    try {
      const page = await request(`/platform/diagnostics?${query}`);
      if (current !== epoch) return;
      total = page.total;
      render(page.items);
      message(page.items.length ? "" : "Сохранённых инцидентов по этим фильтрам нет.");
    } catch (error) {
      if (current !== epoch) return;
      el.diagnosticsList.replaceChildren();
      if (error.status === 401) onSessionLost();
      else if (error.status === 403) setProfile(null);
      else message("Не удалось загрузить журнал. Повторите запрос.", true);
    } finally {
      if (current === epoch) { busy = false; controls(); }
    }
  }

  function render(incidents) {
    el.diagnosticsList.replaceChildren(...incidents.map(incidentRow));
    const first = total ? offset + 1 : 0;
    const last = Math.min(offset + incidents.length, total);
    el.diagnosticsRange.textContent = `${first}–${last} из ${total}`;
    el.diagnosticsPagination.hidden = total <= pageSize;
    controls();
  }

  function incidentRow(incident) {
    const row = document.createElement("article");
    row.className = "diagnostic-row";
    const identity = document.createElement("div");
    const severity = document.createElement("span");
    severity.className = `diagnostic-severity ${incident.severity}`;
    severity.textContent = severityLabel(incident.severity);
    const title = document.createElement("h3");
    title.textContent = incident.code;
    const source = document.createElement("p");
    source.textContent = `${sourceLabel(incident.source)} · ${incident.component} / ${incident.action}`;
    identity.append(severity, title, source);
    const location = document.createElement("div");
    const route = document.createElement("code");
    route.textContent = `${incident.method} ${incident.route}`;
    const type = document.createElement("p");
    type.textContent = incident.error_type || "Ошибка интерфейса без сообщения";
    const id = document.createElement("p");
    id.textContent = `Инцидент ${incident.id}`;
    location.append(route, type, id);
    const timing = document.createElement("div");
    const count = document.createElement("strong");
    count.className = "diagnostic-count";
    count.textContent = `${incident.occurrence_count} ${countLabel(incident.occurrence_count)}`;
    const lastSeen = document.createElement("p");
    lastSeen.textContent = `Последний: ${new Date(incident.last_seen_at).toLocaleString("ru-RU")}`;
    const requestId = document.createElement("p");
    requestId.textContent = `Запрос: ${incident.last_request_id}`;
    timing.append(count, lastSeen, requestId);
    row.append(identity, location, timing);
    return row;
  }

  function controls() {
    for (const control of el.diagnosticsFilters.elements) control.disabled = busy;
    el.diagnosticsPrevious.disabled = busy || offset === 0;
    el.diagnosticsNext.disabled = busy || offset + pageSize >= total;
    el.diagnosticJournal.setAttribute("aria-busy", String(busy));
  }

  el.diagnosticsLink.addEventListener("click", event => { event.preventDefault(); void open(); });
  el.diagnosticsClose.addEventListener("click", () => { el.diagnosticJournal.hidden = true; el.diagnosticsLink.focus(); });
  el.diagnosticsFilters.addEventListener("submit", event => { event.preventDefault(); offset = 0; void load(); });
  el.diagnosticsPrevious.addEventListener("click", () => { offset = Math.max(0, offset - pageSize); void load(); });
  el.diagnosticsNext.addEventListener("click", () => { offset += pageSize; void load(); });

  return { setProfile, reset, open, load };
}

function severityLabel(value) {
  return { critical: "Критическая", error: "Ошибка", warning: "Предупреждение" }[value] || value;
}

function sourceLabel(value) {
  return value === "backend" ? "Backend" : "Интерфейс";
}

function countLabel(value) {
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return "случай";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "случая";
  return "случаев";
}
