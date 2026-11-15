// app.js: what the user has chosen, loading the analyses, and filling in the page.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    area: null, areaLabel: "", start: null, end: null, baseline: [2003, 2022],
    mode: "harmonized", metric: "count", calview: "counts", calgran: "month", tab: "calendar", dataStart: "2001-01-01", dataEnd: null,
    calendarCells: [], weekCells: null, presetIndex: null,
  };
  const UNITS = { harmonized: "hotspots", modis_only: "MODIS hotspots", viirs_raw: "VIIRS hotspots" };
  const MODE_HINT = {
    harmonized: "Harmonized: VIIRS translated to the MODIS scale, so 2001–today is one consistent series.",
    modis_only: "MODIS only: the original Terra + Aqua detections (1 km pixels). Consistent, but MODIS is ending in 2027.",
    viirs_raw: "Raw VIIRS: 375 m detections as reported, from 2012. Not comparable with MODIS years: it sees far more hotspots.",
  };
  const TABS = ["calendar", "patterns", "now"];

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
  function failed(e) {                         // a waking server is not an error: show progress
    if (e instanceof API.ApiError && e.waking) showWaking();
    else showError(e.message);
  }
  function body(extra = {}) {
    return { area: state.area, start: state.start, end: state.end, baseline: state.baseline,
             mode: state.mode, metric: state.metric, ...extra };
  }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  const units = () => (state.metric === "frp" ? "MW of fire power" : UNITS[state.mode]);

  // ---------------------------------------------------------------- shareable links
  // The whole view lives in the address (#area=…&start=…), so a link reopens exactly this view.
  function areaToText(a) {
    if (a.type === "bbox") return `bbox:${a.bbox.join(",")}`;
    if (a.type === "point") return `point:${a.lat},${a.lon},${a.radius_km}`;
    return "poly:" + a.coordinates[0].map(([x, y]) => `${x} ${y}`).join(",");
  }
  function textToArea(t) {
    const [kind, rest] = [t.slice(0, t.indexOf(":")), t.slice(t.indexOf(":") + 1)];
    const nums = (s) => s.split(",").map(Number);
    if (kind === "bbox") { const b = nums(rest); return b.length === 4 && b.every(isFinite) ? { type: "bbox", bbox: b } : null; }
    if (kind === "point") { const [lat, lon, r] = nums(rest); return [lat, lon, r].every(isFinite) ? { type: "point", lat, lon, radius_km: r } : null; }
    if (kind === "poly") {
      const ring = rest.split(",").map((p) => p.trim().split(/\s+/).map(Number));
      return ring.length >= 4 && ring.every((p) => p.length === 2 && p.every(isFinite)) ? { type: "polygon", coordinates: [ring] } : null;
    }
    return null;
  }
  function writeHash() {
    if (!state.area) return;
    const p = new URLSearchParams({
      area: areaToText(state.area), label: state.areaLabel, start: state.start || "", end: state.end || "",
      base: state.baseline.join("-"), mode: state.mode, tab: state.tab, cal: state.calview, gran: state.calgran, metric: state.metric,
    });
    history.replaceState(null, "", `${location.pathname}${location.search}#${p}`);
  }
  function readHash() {
    if (location.hash.length < 2) return null;
    const p = new URLSearchParams(location.hash.slice(1));
    const area = p.get("area") && textToArea(p.get("area"));
    if (!area) return null;
    const iso = /^\d{4}-\d{2}-\d{2}$/;
    const base = (p.get("base") || "").split("-").map(Number);
    return {
      area, label: p.get("label") || "Shared area",
      start: iso.test(p.get("start")) ? p.get("start") : null, end: iso.test(p.get("end")) ? p.get("end") : null,
      baseline: base.length === 2 && base.every((y) => y > 2000 && y < 2100) ? base : null,
      mode: UNITS[p.get("mode")] ? p.get("mode") : null,
      tab: TABS.includes(p.get("tab")) ? p.get("tab") : null,
      cal: ["counts", "anomaly"].includes(p.get("cal")) ? p.get("cal") : null,
      gran: ["month", "week"].includes(p.get("gran")) ? p.get("gran") : null,
      metric: ["count", "frp"].includes(p.get("metric")) ? p.get("metric") : null,
    };
  }

  // ---------------------------------------------------------------- a sleeping server waking up
  let wakingTimer = null;
  function showWaking() {
    $("waking").hidden = false;
    if (wakingTimer) return;
    const poll = async () => {
      try {
        const s = await API.status();
        const d = s.download;
        if (!d.active && !d.error) { location.reload(); return; }
        if (d.error) { $("waking-detail").textContent = `The data couldn't be loaded: ${d.error}`; return; }
        const pct = d.mb_total ? Math.min(99, Math.round(100 * d.mb_done / d.mb_total)) : 5;
        $("waking-fill").style.width = `${Math.max(3, pct)}%`;
        $("waking-detail").textContent = d.file
          ? `Loading ${d.file}: ${Math.round(d.mb_done)}${d.mb_total ? ` of ${d.mb_total}` : ""} MB`
          : "Starting…";
      } catch (_) { $("waking-detail").textContent = "Waiting for the server…"; }
      wakingTimer = setTimeout(poll, 3000);
    };
    poll();
  }

  // ---------------------------------------------------------------- loading
  let runId = 0;
  async function runAll() {
    if (!state.area) return;
    const id = ++runId;
    showError(null);
    writeHash();
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
      state.weekCells = null;                   // weeks are fetched when shown
      await renderCalendar();
      renderPatterns(patterns);
      await renderNow(current);
      CHARTS.longterm(ts, state.mode, state.metric === "frp" ? "MW of fire power per month" : "hotspots per month");
      $("daily-card").hidden = true;
    } catch (e) {
      if (id === runId) failed(e);
    } finally {
      busy(false);
    }
  }

  async function runSummaryOnly() {
    if (!state.area) return;
    showError(null);
    writeHash();
    busy(true);
    try {
      renderSummary(await API.summary(body()));
      renderCalendar();
    } catch (e) { failed(e); } finally { busy(false); }
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
    $("kf-total-label").textContent = state.metric === "frp" ? "Fire power in range" : "Hotspots in range";
    $("kf-total-sub").textContent = allMissing ? "no satellite data for these dates"
      : state.metric === "frp" ? "MW, summed (MODIS scale)"
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

  async function renderCalendar() {
    const weekly = state.calgran === "week";
    $("calendar-title").textContent = weekly ? "Hotspots per week, 2001 → today" : "Hotspots per month, 2001 → today";
    $("calendar-help").textContent = weekly
      ? "Each square is one week (Monday to Sunday). Click (or press Enter on) a week to see its days."
      : "Each square is one month. Click (or press Enter on) a month to see its days.";
    if (!weekly) {
      CAL.months($("calendar"), state.calendarCells, {
        view: state.calview, units: units(), range: [state.start, state.end],
        title: `${state.areaLabel}: ${state.calview === "anomaly" ? "each month vs its normal" : `${units()} per month`}`,
        onPick: openMonth,
      });
      return;
    }
    if (!state.weekCells) {
      busy(true);
      try {
        const r = await API.calendar(body({ start: state.dataStart, end: state.dataEnd, granularity: "week" }));
        state.weekCells = r.cells;
      } catch (e) { failed(e); return; } finally { busy(false); }
    }
    CAL.weeks($("calendar"), state.weekCells, {
      view: state.calview, units: units(), range: [state.start, state.end],
      title: `${state.areaLabel}: ${state.calview === "anomaly" ? "each week vs its normal" : `${units()} per week`}`,
      onPick: openWeek,
    });
  }

  async function openWeek(period) {
    const y = +period.slice(0, 4), w = +period.slice(6);
    const mon = FMT.isoMonday(y, w), sun = new Date(mon);
    sun.setUTCDate(mon.getUTCDate() + 6);
    const start = FMT.iso(mon) < state.dataStart ? state.dataStart : FMT.iso(mon);
    const end = state.dataEnd && FMT.iso(sun) > state.dataEnd ? state.dataEnd : FMT.iso(sun);
    busy(true);
    try {
      const r = await API.calendarDay(body({ start, end, granularity: "day" }));
      $("daily-card").hidden = false;
      const title = `Week ${w} of ${y} (${FMT.weekRange(y, w)}), day by day`;
      $("daily-title").textContent = title;
      CAL.days($("daily"), r.cells, { id: "daily-svg", title: `${state.areaLabel}: ${title}`, units: units() });
      $("daily-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { failed(e); } finally { busy(false); }
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
    } catch (e) { failed(e); } finally { busy(false); }
  }

  function renderPatterns(p) {
    CHARTS.months(p, units());
    CHARTS.years(p, units());
    const fs = p.fire_season;
    const hr = p.high_risk_months.map((m) => FMT.MONTHS[m - 1]).join(", ");
    $("season-text").textContent = fs
      ? `Fire season (shaded): ${FMT.mmdd(fs.start)} to ${FMT.mmdd(fs.end)}, peaking around ${FMT.mmdd(fs.peak)}; it holds ${Math.round(fs.share_of_year * 100)}% of a typical year's hotspots. Highest-risk months (orange): ${hr || "none"}.`
      : "Too few hotspots here to define a fire season.";
    $("weeks-text").textContent = weeksText(p.high_risk_weeks || []);
    const tr = p.trend, te = $("trend-text");
    te.textContent = tr ? `Long-term trend: ${tr.text}` : "Long-term trend: too few complete years to judge.";
    te.className = `trend ${tr ? tr.direction : ""}`;
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

  // [10,11,12,20,21] -> "Mar 2 – Mar 22 and May 11 – May 24 (ISO weeks 10–12, 20–21)"
  function weeksText(weeks) {
    if (!weeks.length) return "";
    const runs = [];
    weeks.forEach((w) => {
      const last = runs[runs.length - 1];
      if (last && w === last[1] + 1) last[1] = w; else runs.push([w, w]);
    });
    const y = new Date().getUTCFullYear();
    const dates = runs.map(([a, b]) => {
      const s = FMT.weekRange(y, a).split(" – ")[0], e = FMT.weekRange(y, b).split(" – ")[1];
      return `${s} – ${e}`;
    });
    const nums = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
    const list = dates.length > 1 ? `${dates.slice(0, -1).join(", ")} and ${dates.at(-1)}` : dates[0];
    return `Highest-risk weeks: ${list} (ISO weeks ${nums}; dates for ${y}).`;
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
    const [r] = await Promise.all([
      API.calendarDay(body({ start: `${cur.month}-01`,
        end: `${cur.month}-${String(cur.days_so_far).padStart(2, "0")}`, granularity: "day" })),
      renderLastMonth(cur),
    ]);
    $("now-daily-title").textContent = `${FMT.MONTHS[+cur.month.slice(5) - 1]} ${cur.month.slice(0, 4)}, day by day vs normal`;
    CAL.days($("now-daily"), r.cells, { id: "now-daily-svg", units: units(),
      title: `${state.areaLabel}: ${FMT.monthLabel(cur.month)} day by day` });
  }

  // In the first week of a month "so far" rests on a few days, so also show the last full month.
  async function renderLastMonth(cur) {
    const el = $("now-prev");
    el.hidden = true;
    if (cur.days_so_far >= 7 || API.MOCK) return;
    const [y, m] = cur.month.split("-").map(Number);
    const asOf = new Date(Date.UTC(y, m - 1, 0)).toISOString().slice(0, 10);   // last day of last month
    try {
      const p = await API.current(body({ start: null, end: null, as_of: asOf }));
      const name = `${FMT.MONTHS[+p.month.slice(5) - 1]} ${p.month.slice(0, 4)}`;
      let txt = `Last full month, ${name}: ${FMT.int(p.value_so_far)} ${units()}`;
      if (p.median_same_days != null) txt += ` vs a typical ${FMT.int(p.median_same_days)}`;
      if (p.pct_of_median != null) txt += ` (${FMT.pct(p.pct_of_median)}${p.pct_of_median >= 1000 ? " normal" : " of normal"})`;
      if (p.rank_among_years) txt += `, #${p.rank_among_years} of ${p.of_years} years`;
      el.textContent = txt + ".";
      el.hidden = false;
    } catch (_) { /* optional extra: skip quietly */ }
  }

  // ---------------------------------------------------------------- measure (count / FRP)
  function setMetric(metric, rerun = true) {
    state.metric = metric;
    document.querySelector(`input[name="metric"][value="${metric}"]`).checked = true;
    const frp = metric === "frp";
    document.querySelectorAll('input[name="mode"]').forEach((r) => {
      r.disabled = frp && r.value !== "harmonized";
      r.parentElement.title = r.disabled ? "Fire power is only available for the harmonized record" : "";
    });
    if (frp && state.mode !== "harmonized") {
      state.mode = "harmonized";
      document.querySelector('input[name="mode"][value="harmonized"]').checked = true;
      $("mode-hint").textContent = MODE_HINT.harmonized;
    }
    if (rerun) runAll();
  }

  // ---------------------------------------------------------------- place search
  let lastSearch = 0;
  async function findPlace(q) {
    const list = $("place-results");
    if (!q) { list.hidden = true; return; }
    const wait = 1100 - (Date.now() - lastSearch);          // Nominatim: at most 1 request/second
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    lastSearch = Date.now();
    list.innerHTML = "<li class='credit'>Searching…</li>";
    list.hidden = false;
    try {
      const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&accept-language=en&q=${encodeURIComponent(q)}`;
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const places = res.ok ? await res.json() : [];
      list.innerHTML = "";
      if (!places.length) list.innerHTML = "<li class='credit'>No place found. Try a town or county name.</li>";
      places.forEach((pl) => {
        const li = document.createElement("li");
        const b = document.createElement("button");
        b.type = "button";
        const short = pl.display_name.split(",").slice(0, 3).join(",").trim();
        b.textContent = `${short} — analyze 50 km around it`;
        b.addEventListener("click", () => {
          const area = { type: "point", lat: +(+pl.lat).toFixed(4), lon: +(+pl.lon).toFixed(4), radius_km: 50 };
          list.hidden = true;
          MAP.show(area);
          setArea(area, `50 km around ${pl.display_name.split(",")[0]}`);
        });
        li.appendChild(b);
        list.appendChild(li);
      });
      const credit = document.createElement("li");
      credit.className = "credit";
      credit.innerHTML = 'Search by <a href="https://nominatim.openstreetmap.org/" target="_blank" rel="noopener">OpenStreetMap Nominatim</a>';
      list.appendChild(credit);
    } catch (_) {
      list.innerHTML = "<li class='credit'>Place search is unavailable right now; draw on the map instead.</li>";
    }
  }

  // ---------------------------------------------------------------- one-page briefing
  let briefingHidden = null;
  function prepareBriefing() {
    document.body.classList.add("briefing");
    $("print-meta").textContent = `FireBridge briefing · printed ${new Date().toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })} · ${location.href}`;
    // both tabs on the page: a chart in a hidden tab was drawn at zero size and would print blank
    briefingHidden = ["panel-calendar", "panel-now"].map((id) => [id, $(id).hidden]);
    briefingHidden.forEach(([id]) => { $(id).hidden = false; });
    // draw charts at once (no animation) so the printed page never catches them half-drawn
    Object.values(CHARTS.charts).forEach((c) => { c.options.animation = false; c.resize(); c.update("none"); });
  }
  function endBriefing() {
    document.body.classList.remove("briefing");
    if (briefingHidden) briefingHidden.forEach(([id, h]) => { $(id).hidden = h; });
    briefingHidden = null;
    Object.values(CHARTS.charts).forEach((c) => c.resize());
  }
  window.FireBridgeBriefing = { prepare: prepareBriefing, end: endBriefing };   // used by scripts/check_site.py
  function printBriefing() {
    prepareBriefing();
    window.addEventListener("afterprint", endBriefing, { once: true });
    setTimeout(() => window.print(), 250);
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

  // ---------------------------------------------------------------- tabs
  let tabEls = [];
  function selectTab(name, focus = false) {
    state.tab = name;
    tabEls.forEach((t) => {
      const on = t.id === `tab-${name}`;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
      if (on && focus) t.focus();
    });
    Object.values(CHARTS.charts).forEach((c) => c.resize());
    writeHash();
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
      writeHash();
    }));
    document.querySelectorAll('input[name="calgran"]').forEach((r) => r.addEventListener("change", () => {
      state.calgran = r.value;
      $("daily-card").hidden = true;
      renderCalendar();
      writeHash();
    }));

    // tabs (arrow keys move between them, as in the ARIA tabs pattern)
    tabEls = [...document.querySelectorAll('[role="tab"]')];
    tabEls.forEach((t, i) => {
      const name = t.id.replace("tab-", "");
      t.addEventListener("click", () => selectTab(name));
      t.addEventListener("keydown", (e) => {
        const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (!d) return;
        const n = tabEls[(i + d + tabEls.length) % tabEls.length];
        selectTab(n.id.replace("tab-", ""), true);
      });
    });

    // measure: hotspot count or fire power (FRP exists only for the harmonized record)
    document.querySelectorAll('input[name="metric"]').forEach((r) => r.addEventListener("change", () => setMetric(r.value)));

    // place search (OpenStreetMap Nominatim: one request per search, never while typing)
    $("place-form").addEventListener("submit", (e) => { e.preventDefault(); findPlace($("place-q").value.trim()); });

    // more downloads + briefing
    $("dl-geojson").addEventListener("click", () => download("export/hotspots.geojson", "firebridge_hotspots.geojson", $("dl-geojson")));
    $("dl-kml").addEventListener("click", () => download("export/hotspots.kml", "firebridge_hotspots.kml", $("dl-kml")));
    $("print-briefing").addEventListener("click", printBriefing);

    // shareable link
    $("copy-link").addEventListener("click", async () => {
      writeHash();
      const btn = $("copy-link");
      try { await navigator.clipboard.writeText(location.href); btn.textContent = "Link copied"; }
      catch (_) { window.prompt("Copy this link:", location.href); }
      setTimeout(() => { btn.textContent = "Copy link"; }, 1800);
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
    catch (e) { failed(e); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  // apply a view from a shared link (settings first, then the area, which runs the analyses)
  function applyShared(v) {
    if (v.baseline) { state.baseline = v.baseline; $("base0").value = v.baseline[0]; $("base1").value = v.baseline[1]; }
    if (v.mode) { state.mode = v.mode; document.querySelector(`input[name="mode"][value="${v.mode}"]`).checked = true; $("mode-hint").textContent = MODE_HINT[v.mode]; }
    if (v.cal) { state.calview = v.cal; document.querySelector(`input[name="calview"][value="${v.cal}"]`).checked = true; }
    if (v.metric) setMetric(v.metric, false);
    if (v.gran) { state.calgran = v.gran; document.querySelector(`input[name="calgran"][value="${v.gran}"]`).checked = true; }
    if (v.tab) selectTab(v.tab);
    setDates(v.start || `${state.dataEnd.slice(0, 4)}-01-01`, v.end || state.dataEnd);
    MAP.show(v.area);
    setArea(v.area, v.label);
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
      const shared = readHash();
      if (shared) applyShared(shared);
      else if (presets.length) applyPreset(presets[0], 0);
      else {
        setDates(`${state.dataEnd.slice(0, 4)}-01-01`, state.dataEnd);
        const area = { type: "bbox", bbox: [-100, 30, -96, 33] };
        MAP.show(area);
        setArea(area, "Central Texas");
      }
    } catch (e) {
      failed(e);
    }
  }
  start();
})();
