// app.js: what the user has chosen, loading the analyses, and filling in the page.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    area: null, areaLabel: "", start: null, end: null, baseline: [2003, 2022],
    mode: "harmonized", calview: "counts", dataStart: "2001-01-01", dataEnd: null,
    calendarCells: [], presetIndex: null,
  };
  const UNITS = { harmonized: "hotspots", modis_only: "MODIS hotspots", viirs_raw: "VIIRS hotspots" };
  const MODE_HINT = {
    harmonized: "Harmonized: VIIRS translated to the MODIS scale, so 2001–today is one consistent series.",
    modis_only: "MODIS only: the original Terra + Aqua detections (1 km pixels). Consistent, but MODIS is ending in 2027.",
    viirs_raw: "Raw VIIRS: 375 m detections as reported, from 2012. Not comparable with MODIS years: it sees far more hotspots.",
  };

  // ---------------------------------------------------------------- helpers
  let pending = 0;
  function busy(on) {
    pending += on ? 1 : -1;
    $("loading").hidden = pending <= 0;
  }
  function showError(msg) {
    const b = $("error-banner");
    b.textContent = msg || "";
    b.hidden = !msg;
  }
  function body(extra = {}) {
    return { area: state.area, start: state.start, end: state.end, baseline: state.baseline,
             mode: state.mode, metric: "count", ...extra };
  }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  const units = () => UNITS[state.mode];

  // ---------------------------------------------------------------- loading
  let runId = 0;
  async function runAll() {
    if (!state.area) return;
    const id = ++runId;
    showError(null);
    busy(true);
    try {
      const [summary, cal, patterns, current, ts] = await Promise.all([
        API.summary(body()),
        API.calendar(body({ start: state.dataStart, end: state.dataEnd, granularity: "month" })),
        API.patterns(body()),
        API.current(body({ start: null, end: null })),
        API.timeseries(body()),
      ]);
      if (id !== runId) return;                 // a newer request has started
      renderSummary(summary);
      state.calendarCells = cal.cells;
      state.calUnits = cal.units;
      renderCalendar();
      renderPatterns(patterns);
      await renderNow(current);
      CHARTS.longterm(ts, state.mode);
      $("daily-card").hidden = true;
    } catch (e) {
      if (id === runId) showError(e.message);
    } finally {
      busy(false);
    }
  }

  async function runSummaryOnly() {
    if (!state.area) return;
    showError(null);
    busy(true);
    try {
      renderSummary(await API.summary(body()));
      renderCalendar();
    } catch (e) { showError(e.message); } finally { busy(false); }
  }

  // ---------------------------------------------------------------- render
  function renderSummary(s) {
    const k = s.key_figures;
    $("area-label").textContent = state.areaLabel;
    const km = s.area_km2 ? `${FMT.int(s.area_km2)} km²` : "";
    $("range-label").textContent = `${FMT.date(s.range.start)} – ${FMT.date(s.range.end)} · ${km} · ` +
      `normal = median of ${state.baseline[0]}–${state.baseline[1]}`;
    // every day missing (e.g. raw VIIRS before 2012): that's "no data", not "0 fires"
    const days = Math.round((Date.parse(s.range.end) - Date.parse(s.range.start)) / 864e5) + 1;
    const allMissing = s.missing_days >= days;
    $("kf-total").textContent = allMissing ? "No data" : FMT.int(k.total_hotspots);
    $("kf-total-sub").textContent = allMissing ? "no satellite data for these dates"
      : state.mode === "harmonized" ? "MODIS-scale hotspots" : units();
    $("kf-pct").textContent = FMT.pct(k.pct_of_median);
    $("kf-pct").classList.toggle("hot", k.pct_of_median >= 150);
    $("kf-pct-sub").textContent = FMT.pctSub(k.pct_of_median);
    $("kf-month").textContent = FMT.monthLabel(k.busiest_month);
    $("kf-year").textContent = k.busiest_year ?? "–";
    const multiYear = s.range.end.slice(0, 4) !== s.range.start.slice(0, 4);
    $("kf-year-sub").textContent = multiYear ? "in range" : "on record";
    const fs = k.fire_season;
    $("kf-season").textContent = fs ? `${FMT.MON[+fs.start.slice(0, 2) - 1]}–${FMT.MON[+fs.end.slice(0, 2) - 1]}` : "–";
    $("kf-season-sub").textContent = fs ? `peak ${FMT.mmdd(fs.peak)}` : "";
    $("summary-text").textContent = s.summary_text;
  }

  function renderCalendar() {
    CAL.months($("calendar"), state.calendarCells, {
      view: state.calview, units: units(), range: [state.start, state.end],
      title: `${state.areaLabel}: ${state.calview === "anomaly" ? "each month vs its normal" : `${units()} per month`}`,
      onPick: openMonth,
    });
  }

  async function openMonth(period) {
    const [y, m] = period.split("-").map(Number);
    const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
    const end = state.dataEnd && last > state.dataEnd ? state.dataEnd : last;
    busy(true);
    try {
      const r = await API.calendarDay(body({ start: `${period}-01`, end, granularity: "day" }));
      $("daily-card").hidden = false;
      const title = `${FMT.MONTHS[m - 1]} ${y}, day by day`;
      $("daily-title").textContent = title;
      CAL.days($("daily"), r.cells, { id: "daily-svg", title: `${state.areaLabel}: ${title}`, units: units() });
      $("daily-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { showError(e.message); } finally { busy(false); }
  }

  function renderPatterns(p) {
    CHARTS.months(p, units());
    CHARTS.years(p, units());
    const fs = p.fire_season;
    const hr = p.high_risk_months.map((m) => FMT.MONTHS[m - 1]).join(", ");
    $("season-text").textContent = fs
      ? `Fire season (shaded): ${FMT.mmdd(fs.start)} to ${FMT.mmdd(fs.end)}, peaking around ${FMT.mmdd(fs.peak)}; it holds ${Math.round(fs.share_of_year * 100)}% of a typical year's hotspots. Highest-risk months (orange): ${hr || "none"}.`
      : "Too few hotspots here to define a fire season.";
    const top = p.years_ranked.slice(0, 3).map((r) => `${r.year} (${FMT.int(r.total)})`).join(", ");
    $("years-text").textContent = top ? `Busiest years: ${top}. Only complete years are ranked.` : "No complete years to rank.";
    const row = $("chance-row");
    row.innerHTML = "";
    p.chance_unusual_month.forEach((c) => {
      const v = c.pct_years_above_normal;
      const bg = v == null ? "#f2f2f2" : d3.interpolateOranges(0.08 + Math.min(v, 50) / 50 * 0.75);
      const d = document.createElement("div");
      d.className = "chance";
      d.style.background = bg;
      d.style.color = FMT.textOn(bg);
      d.setAttribute("role", "img");
      d.setAttribute("aria-label", `${FMT.MONTHS[c.month - 1]}: ${v == null ? "not enough data" : v + "% of years unusually busy"}`);
      d.innerHTML = `<b>${v == null ? "–" : v + "%"}</b>${FMT.MON[c.month - 1]}`;
      row.appendChild(d);
    });
  }

  async function renderNow(cur) {
    $("now-title").textContent = `${FMT.MONTHS[+cur.month.slice(5) - 1]} ${cur.month.slice(0, 4)} so far (days 1–${cur.days_so_far})`;
    $("now-pct").textContent = FMT.pct(cur.pct_of_median);
    $("now-pct-sub").textContent = cur.pct_of_median == null ? "can't compare with normal"
      : (cur.pct_of_median >= 1000 ? "the median for these days" : "of the median for these days");
    $("now-rank").textContent = cur.rank_among_years
      ? `#${cur.rank_among_years} of ${cur.of_years} years${cur.provisional ? " · provisional" : ""}` : "";
    $("now-text").textContent = cur.summary_text;
    CHARTS.now(cur, units());
    const r = await API.calendarDay(body({ start: `${cur.month}-01`,
      end: `${cur.month}-${String(cur.days_so_far).padStart(2, "0")}`, granularity: "day" }));
    $("now-daily-title").textContent = `${FMT.MONTHS[+cur.month.slice(5) - 1]} ${cur.month.slice(0, 4)}, day by day vs normal`;
    CAL.days($("now-daily"), r.cells, { id: "now-daily-svg", units: units(),
      title: `${state.areaLabel}: ${FMT.monthLabel(cur.month)} day by day` });
  }

  // ---------------------------------------------------------------- choosing an area
  function setArea(area, label, presetIndex = null) {
    state.area = area;
    state.areaLabel = label;
    state.presetIndex = presetIndex;
    document.querySelectorAll(".preset").forEach((b, i) => b.setAttribute("aria-pressed", String(i === presetIndex)));
    runAll();
  }

  function setDates(start, end) {
    state.start = start; state.end = end;
    $("start").value = start; $("end").value = end;
  }

  function applyPreset(p, i) {
    setDates(p.start, p.end);
    const area = { type: "bbox", bbox: p.bbox };
    MAP.show(area);
    setArea(area, p.name, i);
  }

  // ---------------------------------------------------------------- wiring
  function wire() {
    $("bbox-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const area = { type: "bbox", bbox: ["w", "s", "e", "n"].map((k) => +f.get(k)) };
      MAP.show(area);
      setArea(area, `Box ${area.bbox.join(", ")}`);
    });
    $("point-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const area = { type: "point", lat: +f.get("lat"), lon: +f.get("lon"), radius_km: +f.get("r") };
      MAP.show(area);
      setArea(area, `${area.radius_km} km around ${area.lat}, ${area.lon}`);
    });

    const onDates = debounce(() => {
      if (!$("start").value || !$("end").value) return;
      state.start = $("start").value; state.end = $("end").value;
      runSummaryOnly();
    }, 350);
    $("start").addEventListener("change", onDates);
    $("end").addEventListener("change", onDates);
    document.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", () => {
      const end = new Date(state.dataEnd + "T00:00:00Z");
      let start;
      if (b.dataset.range === "12m") { start = new Date(end); start.setUTCFullYear(end.getUTCFullYear() - 1); start.setUTCDate(start.getUTCDate() + 1); }
      else if (b.dataset.range === "ytd") start = new Date(Date.UTC(end.getUTCFullYear(), 0, 1));
      else start = new Date(state.dataStart + "T00:00:00Z");
      setDates(FMT.iso(start), state.dataEnd);
      runSummaryOnly();
    }));

    const onBaseline = debounce(() => {
      const a = +$("base0").value, b = +$("base1").value;
      if (!a || !b) return;
      state.baseline = [Math.min(a, b), Math.max(a, b)];
      runAll();
    }, 500);
    $("base0").addEventListener("change", onBaseline);
    $("base1").addEventListener("change", onBaseline);

    document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
      state.mode = r.value;
      $("mode-hint").textContent = MODE_HINT[state.mode];
      runAll();
    }));
    document.querySelectorAll('input[name="calview"]').forEach((r) => r.addEventListener("change", () => {
      state.calview = r.value;
      renderCalendar();
    }));

    // tabs (arrow keys move between them, as in the ARIA tabs pattern)
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    function select(tab) {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", on);
        t.tabIndex = on ? 0 : -1;
        $(t.getAttribute("aria-controls")).hidden = !on;
      });
      Object.values(CHARTS.charts).forEach((c) => c.resize());
    }
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (!d) return;
        const n = tabs[(i + d + tabs.length) % tabs.length];
        select(n); n.focus();
      });
    });

    // downloads
    document.querySelectorAll("[data-png]").forEach((b) => b.addEventListener("click", () => {
      const id = b.dataset.png;
      const slug = state.areaLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
      const name = `firebridge_${id.replace(/-svg$|^chart-/, "")}_${slug}.png`;
      const el = document.getElementById(id);
      if (el && el.tagName.toLowerCase() === "svg") CHARTS.downloadSvg(el, name);
      else CHARTS.downloadCanvas(id, name);
    }));
    $("dl-hotspots").addEventListener("click", () => download("export/hotspots.csv", "firebridge_hotspots.csv", $("dl-hotspots")));
    $("dl-series").addEventListener("click", () => download("export/series.csv", "firebridge_series.csv", $("dl-series")));
  }

  async function download(endpoint, name, btn) {
    if (!state.area) return;
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "Preparing…";
    try { await API.downloadCSV(endpoint, body({ granularity: "day" }), name); }
    catch (e) { showError(e.message); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  // ---------------------------------------------------------------- start
  async function start() {
    if (API.MOCK) $("mock-banner").hidden = false;
    wire();
    try {
      const [{ regions }, presets] = await Promise.all([API.regions(), API.presets().catch(() => [])]);
      state.dataStart = regions.map((r) => r.start).sort()[0];
      state.dataEnd = regions.map((r) => r.live_end).sort().slice(-1)[0];
      ["start", "end"].forEach((id) => { $(id).min = state.dataStart; $(id).max = state.dataEnd; });
      MAP.init(regions, (area, label) => setArea(area, label));
      const box = $("preset-buttons");
      presets.forEach((p, i) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "preset"; b.setAttribute("aria-pressed", "false");
        b.title = p.why;
        const name = p.name.replace(/,\s*([A-Z][a-z]{2}.*\d{4})$/, "");
        const when = (p.name.match(/,\s*([A-Z][a-z]{2}.*\d{4})$/) || [])[1] || `${p.start} – ${p.end}`;
        b.innerHTML = `<strong></strong><span></span>`;
        b.querySelector("strong").textContent = name;
        b.querySelector("span").textContent = when;
        b.addEventListener("click", () => applyPreset(p, i));
        box.appendChild(b);
      });
      if (presets.length) applyPreset(presets[0], 0);
      else {
        setDates(`${state.dataEnd.slice(0, 4)}-01-01`, state.dataEnd);
        const area = { type: "bbox", bbox: [-100, 30, -96, 33] };
        MAP.show(area);
        setArea(area, "Central Texas");
      }
    } catch (e) {
      showError(e.message);
    }
  }
  start();
})();
