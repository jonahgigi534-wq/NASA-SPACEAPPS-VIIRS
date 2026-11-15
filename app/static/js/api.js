// api.js: the only place that talks to the server.
// With ?mock=1 in the URL it reads sample JSON from mock/ instead (for building the UI offline).
const API = (() => {
  const params = new URLSearchParams(location.search);
  const MOCK = params.get("mock") === "1";
  // ?api=http://127.0.0.1:8000 lets the page call a backend on another port while developing.
  const BASE = (params.get("api") || "").replace(/\/$/, "");

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
    // 503 + "still downloading" = a freshly woken server loading its data, not a real error
    get waking() { return this.status === 503 && /still downloading/i.test(this.message); }
  }

  async function getJSON(path) {
    const r = await fetch(BASE + path);
    return handle(r);
  }

  async function handle(r) {
    let body = null;
    try { body = await r.json(); } catch (_) { /* not JSON */ }
    if (!r.ok) {
      throw new ApiError((body && body.error) || `The server answered ${r.status}. Please try again.`, r.status);
    }
    return body;
  }

  async function post(endpoint, body) {
    if (MOCK) {
      const r = await fetch(`mock/${endpoint}.json`);
      return handle(r);
    }
    const r = await fetch(`${BASE}/api/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    return handle(r);
  }

  // POST that returns a CSV file: save it with the server's file name.
  async function downloadCSV(endpoint, body, fallbackName) {
    let r;
    if (MOCK) r = await fetch(`mock/${endpoint.replace("export/", "").replace(".csv", "")}.csv`);
    else r = await fetch(`${BASE}/api/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!r.ok) await handle(r);
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const name = (cd.match(/filename="?([^"]+)"?/) || [])[1] || fallbackName;
    saveBlob(blob, name);
  }

  function saveBlob(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  return {
    MOCK, ApiError, saveBlob, downloadCSV,
    regions: () => MOCK ? fetch("mock/regions.json").then(handle) : getJSON("/api/regions"),
    status: () => getJSON("/api/status"),
    presets: () => MOCK ? fetch("mock/presets.json").then(handle) : getJSON("/content/presets.json"),
    summary: (b) => post("summary", b),
    calendar: (b) => post("calendar", b),
    calendarDay: (b) => MOCK ? fetch("mock/calendar_day.json").then(handle) : post("calendar", b),
    patterns: (b) => post("patterns", b),
    current: (b) => post("current", b),
    timeseries: (b) => post("timeseries", b),
  };
})();
