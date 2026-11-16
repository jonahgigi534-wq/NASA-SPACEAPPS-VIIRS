// app.js: what the user has chosen, loading the analyses, and filling in the page.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    area: null, areaLabel: "", start: null, end: null, baseline: [2003, 2022],
    mode: "harmonized", metric: "count", calview: "counts", calgran: "month", tab: "calendar", dataStart: "2001-01-01", dataEnd: null,
    calendarCells: [], weekCells: null, presetIndex: null, mapview: "counts",
  };
  const ES = I18N.es, t = I18N.t;
  const UNITS = ES ? { harmonized: "focos de calor", modis_only: "focos MODIS", viirs_raw: "focos VIIRS" }
                   : { harmonized: "hotspots", modis_only: "MODIS hotspots", viirs_raw: "VIIRS hotspots" };
  const MODE_HINT = {
    harmonized: I18N.t("Harmonized: VIIRS translated to the MODIS scale, so 2001–today is one consistent series."),
    modis_only: I18N.t("MODIS only: the original Terra + Aqua detections (1 km pixels). Consistent, but MODIS is ending in 2027."),
    viirs_raw: I18N.t("Raw VIIRS: 375 m detections as reported, from 2012. Not comparable with MODIS years: it sees far more hotspots."),
  };
  const TABS = ["calendar", "patterns", "now", "fires"];

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
             mode: state.mode, metric: state.metric, lang: I18N.lang, ...extra };
  }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  const units = () => (state.metric === "frp" ? (ES ? "MW de potencia de fuego" : "MW of fire power") : UNITS[state.mode]);

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
      defaultCompare();
      resetMapMonths();
      refreshMap();
      state.calendarCells = cal.cells;
      state.calUnits = cal.units;
      state.weekCells = null;                   // weeks are fetched when shown
      await renderCalendar();
      renderPatterns(patterns);
      await renderNow(current);
      CHARTS.longterm(ts, state.mode, ES ? (state.metric === "frp" ? "MW de potencia de fuego por mes" : "focos por mes") : (state.metric === "frp" ? "MW of fire power per month" : "hotspots per month"));
      firesKey = null;
      MAP.clearHighlight();
      if (state.tab === "fires") loadFires();
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
      defaultCompare();
      resetMapMonths();
      refreshMap();
      renderCalendar();
    } catch (e) { failed(e); } finally { busy(false); }
  }

  // ---------------------------------------------------------------- render
  function renderSummary(s) {
    const k = s.key_figures;
    $("area-label").textContent = state.areaLabel;
    const km = s.area_km2 ? `${FMT.int(s.area_km2)} km²` : "";
    $("range-label").textContent = `${FMT.date(s.range.start)} – ${FMT.date(s.range.end)} · ${km} · ` +
      (ES ? `normal = mediana de ${state.baseline[0]}–${state.baseline[1]}` : `normal = median of ${state.baseline[0]}–${state.baseline[1]}`);
    // every day missing (e.g. raw VIIRS before 2012): that's "no data", not "0 fires"
    const days = Math.round((Date.parse(s.range.end) - Date.parse(s.range.start)) / 864e5) + 1;
    const allMissing = s.missing_days >= days;
    $("kf-total").textContent = allMissing ? t("No data") : FMT.int(k.total_hotspots);
    $("kf-total-label").textContent = t(state.metric === "frp" ? "Fire power in range" : "Hotspots in range");
    $("kf-total-sub").textContent = allMissing ? t("no satellite data for these dates")
      : state.metric === "frp" ? t("MW, summed (MODIS scale)")
      : state.mode === "harmonized" ? t("MODIS-scale hotspots") : units();
    $("kf-pct").textContent = FMT.pct(k.pct_of_median);
    $("kf-pct").classList.toggle("hot", k.pct_of_median >= 150);
    $("kf-pct-sub").textContent = FMT.pctSub(k.pct_of_median);
    $("kf-month").textContent = FMT.monthLabel(k.busiest_month);
    $("kf-year").textContent = k.busiest_year ?? "–";
    const multiYear = s.range.end.slice(0, 4) !== s.range.start.slice(0, 4);
    $("kf-year-sub").textContent = t(multiYear ? "in range" : "on record");
    const fs = k.fire_season;
    $("kf-season").textContent = fs ? `${FMT.MON[+fs.start.slice(0, 2) - 1]}–${FMT.MON[+fs.end.slice(0, 2) - 1]}` : "–";
    $("kf-season-sub").textContent = fs ? `${ES ? "pico" : "peak"} ${FMT.mmdd(fs.peak)}` : "";
    $("summary-text").textContent = s.summary_text;
  }

  async function renderCalendar() {
    const weekly = state.calgran === "week";
    $("calendar-title").textContent = t(weekly ? "Hotspots per week, 2001 → today" : "Hotspots per month, 2001 → today");
    $("calendar-help").textContent = weekly
      ? t("Each square is one week (Monday to Sunday). Click (or press Enter on) a week to see its days.")
      : t("Each square is one month. Click (or press Enter on) a month to see its days.");
    if (!weekly) {
      CAL.months($("calendar"), state.calendarCells, {
        view: state.calview, units: units(), range: [state.start, state.end],
        title: `${state.areaLabel}: ${state.calview === "anomaly" ? (ES ? "cada mes vs su normal" : "each month vs its normal") : `${units()} ${ES ? "por mes" : "per month"}`}`,
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
      title: `${state.areaLabel}: ${state.calview === "anomaly" ? (ES ? "cada semana vs su normal" : "each week vs its normal") : `${units()} ${ES ? "por semana" : "per week"}`}`,
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
      const title = ES ? `Semana ${w} de ${y} (${FMT.weekRange(y, w)}), día a día` : `Week ${w} of ${y} (${FMT.weekRange(y, w)}), day by day`;
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
      const title = ES ? `${FMT.MONTHS[m - 1]} de ${y}, día a día` : `${FMT.MONTHS[m - 1]} ${y}, day by day`;
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
      ? (ES ? `Temporada de incendios (sombreada): del ${FMT.mmdd(fs.start)} al ${FMT.mmdd(fs.end)}, con el pico hacia el ${FMT.mmdd(fs.peak)}; reúne el ${Math.round(fs.share_of_year * 100)} % de los focos de un año típico. Meses de mayor riesgo (naranja): ${hr ? hr.replace(/, ([^,]*)$/, " y $1") : "ninguno"}.`
            : `Fire season (shaded): ${FMT.mmdd(fs.start)} to ${FMT.mmdd(fs.end)}, peaking around ${FMT.mmdd(fs.peak)}; it holds ${Math.round(fs.share_of_year * 100)}% of a typical year's hotspots. Highest-risk months (orange): ${hr || "none"}.`)
      : t("Too few hotspots here to define a fire season.");
    $("weeks-text").textContent = weeksText(p.high_risk_weeks || []);
    const tr = p.trend, te = $("trend-text");
    te.textContent = tr ? `${ES ? "Tendencia a largo plazo" : "Long-term trend"}: ${tr.text}` : t("Long-term trend: too few complete years to judge.");
    te.className = `trend ${tr ? tr.direction : ""}`;
    const top = p.years_ranked.slice(0, 3).map((r) => `${r.year} (${FMT.int(r.total)})`).join(", ");
    $("years-text").textContent = top ? (ES ? `Años con más fuego: ${top}. Solo se ordenan los años completos.` : `Busiest years: ${top}. Only complete years are ranked.`) : t("No complete years to rank.");
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
    return ES ? `Semanas de mayor riesgo: ${list.replace(/ and /g, " y ")} (semanas ISO ${nums}; fechas de ${y}).`
              : `Highest-risk weeks: ${list} (ISO weeks ${nums}; dates for ${y}).`;
  }

  async function renderNow(cur) {
    $("now-title").textContent = ES ? `${FMT.MONTHS[+cur.month.slice(5) - 1]} de ${cur.month.slice(0, 4)} hasta ahora (días 1–${cur.days_so_far})`
      : `${FMT.MONTHS[+cur.month.slice(5) - 1]} ${cur.month.slice(0, 4)} so far (days 1–${cur.days_so_far})`;
    $("now-pct").textContent = FMT.pct(cur.pct_of_median);
    $("now-pct-sub").textContent = t(cur.pct_of_median == null ? "can't compare with normal"
      : (cur.pct_of_median >= 1000 ? "the median for these days" : "of the median for these days"));
    $("now-rank").textContent = cur.rank_among_years
      ? (ES ? `n.º ${cur.rank_among_years} de ${cur.of_years} años${cur.provisional ? " · provisional" : ""}`
            : `#${cur.rank_among_years} of ${cur.of_years} years${cur.provisional ? " · provisional" : ""}`) : "";
    $("now-text").textContent = cur.summary_text;
    CHARTS.now(cur, units());
    const [r] = await Promise.all([
      API.calendarDay(body({ start: `${cur.month}-01`,
        end: `${cur.month}-${String(cur.days_so_far).padStart(2, "0")}`, granularity: "day" })),
      renderLastMonth(cur),
    ]);
    $("now-daily-title").textContent = ES ? `${FMT.MONTHS[+cur.month.slice(5) - 1]} de ${cur.month.slice(0, 4)}, día a día vs lo normal`
      : `${FMT.MONTHS[+cur.month.slice(5) - 1]} ${cur.month.slice(0, 4)}, day by day vs normal`;
    CAL.days($("now-daily"), r.cells, { id: "now-daily-svg", units: units(),
      title: `${state.areaLabel}: ${FMT.monthLabel(cur.month)} ${ES ? "día a día" : "day by day"}` });
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
      const name = `${FMT.MONTHS[+p.month.slice(5) - 1]}${ES ? " de" : ""} ${p.month.slice(0, 4)}`;
      let txt = ES ? `Último mes completo, ${name}: ${FMT.int(p.value_so_far)} ${units()}`
                   : `Last full month, ${name}: ${FMT.int(p.value_so_far)} ${units()}`;
      if (p.median_same_days != null) txt += ES ? ` frente a ${FMT.int(p.median_same_days)} lo típico` : ` vs a typical ${FMT.int(p.median_same_days)}`;
      if (p.pct_of_median != null) txt += ` (${FMT.pct(p.pct_of_median)}${p.pct_of_median >= 1000 ? (ES ? " lo normal" : " normal") : (ES ? " de lo normal" : " of normal")})`;
      if (p.rank_among_years) txt += ES ? `, n.º ${p.rank_among_years} de ${p.of_years} años` : `, #${p.rank_among_years} of ${p.of_years} years`;
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

  // ---------------------------------------------------------------- fire on the map
  const mapCache = new Map();
  let mapMonths = [], playTimer = null, mapReq = 0;
  function resetMapMonths() {
    mapMonths = [];
    if (state.start && state.end) {
      let d = new Date(state.start.slice(0, 7) + "-01T00:00:00Z");
      const last = state.end.slice(0, 7);
      while (FMT.iso(d).slice(0, 7) <= last && mapMonths.length < 400) {
        mapMonths.push(FMT.iso(d).slice(0, 7));
        d.setUTCMonth(d.getUTCMonth() + 1);
      }
    }
    const slider = $("map-month");
    slider.max = String(mapMonths.length);
    slider.value = "0";
    stopPlay();
    $("map-month-label").textContent = t("All selected dates");
  }
  async function refreshMap() {
    if (!state.area) return;
    const view = state.mapview;
    if (view === "off") { MAP.showCells(null, "off"); return; }
    const i = +$("map-month").value;
    let start = state.start, end = state.end, caption = t("All selected dates");
    if (i > 0 && mapMonths[i - 1]) {
      const m = mapMonths[i - 1];
      const monthEnd = FMT.iso(new Date(Date.UTC(+m.slice(0, 4), +m.slice(5, 7), 0)));
      start = `${m}-01` < state.start ? state.start : `${m}-01`;
      end = monthEnd > state.end ? state.end : monthEnd;
      caption = FMT.monthLabel(m);
    }
    $("map-month-label").textContent = caption;
    const b = body({ start, end });
    const key = JSON.stringify(b);
    const id = ++mapReq;
    try {
      let data = mapCache.get(key);
      if (!data) {
        data = await API.cells(b);
        mapCache.set(key, data);
        if (mapCache.size > 200) mapCache.delete(mapCache.keys().next().value);
      }
      if (id !== mapReq) return;                      // a newer month was asked for meanwhile
      MAP.showCells(data, view, units(), `${caption}: ${view === "anomaly" ? "vs normal" : units()}`);
    } catch (_) { /* the map layer is an extra; the analyses still show */ }
  }
  function stopPlay() {
    if (playTimer) clearInterval(playTimer);
    playTimer = null;
    $("map-play").textContent = "▶";
    $("map-play").setAttribute("aria-label", "Play the selected dates month by month");
  }
  function togglePlay() {
    if (playTimer) { stopPlay(); return; }
    if (!mapMonths.length) return;
    const slider = $("map-month");
    if (+slider.value >= mapMonths.length) slider.value = "0";
    $("map-play").textContent = "⏸";
    $("map-play").setAttribute("aria-label", "Pause");
    const step = () => {
      let next = +slider.value + 1;
      if (next > mapMonths.length) next = 1;          // loop, like a radar animation
      slider.value = String(next);
      refreshMap();
      prefetchMonth(next + 1 > mapMonths.length ? 1 : next + 1);
    };
    step();
    playTimer = setInterval(step, PLAY_MS / playSpeed);
  }
  // playback speed (1x, 2x, 4x), and fetching the next month ahead so playback doesn't stall
  const PLAY_MS = 1200;
  let playSpeed = 1;
  function cycleSpeed() {
    playSpeed = playSpeed === 1 ? 2 : playSpeed === 2 ? 4 : 1;
    $("map-speed").textContent = `${playSpeed}x`;
    if (playTimer) { stopPlay(); togglePlay(); }
  }
  function prefetchMonth(i) {
    const m = mapMonths[i - 1];
    if (!m || !state.area || state.mapview === "off") return;
    const monthEnd = FMT.iso(new Date(Date.UTC(+m.slice(0, 4), +m.slice(5, 7), 0)));
    const b = body({ start: `${m}-01` < state.start ? state.start : `${m}-01`, end: monthEnd > state.end ? state.end : monthEnd });
    const key = JSON.stringify(b);
    if (!mapCache.has(key)) API.cells(b).then((d) => mapCache.set(key, d)).catch(() => {});
  }

  // ---------------------------------------------------------------- fires vs past fires
  let firesKey = null;
  async function loadFires() {
    const key = JSON.stringify([state.area, state.mode]);
    if (key === firesKey) return;
    firesKey = key;
    $("fires-text").textContent = t("Grouping hotspots into fire clusters…");
    busy(true);
    try {
      const j = await API.fires(body({ start: null, end: null, metric: "count" }));
      if (key !== firesKey) return;
      renderFires(j);
    } catch (e) {
      firesKey = null;
      $("fires-text").textContent = e.message;
    } finally { busy(false); }
  }
  function renderFires(j) {
    const u = UNITS[state.mode];
    $("fires-text").textContent = j.summary_text || "";
    $("fires-rule").textContent = ES
      ? `Un grupo de incendios = celdas de 0,1° con focos que se tocan el mismo día o con hasta 2 días de diferencia; ` +
        `se omiten los grupos de menos de ${j.min_hotspots} focos. ${FMT.int(j.clusters_total)} grupos en esta zona.`
      : `A fire cluster = ${j.link_rule}; clusters under ${j.min_hotspots} hotspots are left out. ` +
        `${FMT.int(j.clusters_total)} clusters in this area.`;
    if (j.all.length) CHARTS.fires(j, u);
    const head = `<thead><tr><th scope="col">${t("Dates")}</th><th scope="col" class="num">${t("Days")}</th><th scope="col" class="num">${u}</th>` +
      `<th scope="col" class="num">${t("Fire power (MW)")}</th><th scope="col" class="num">${t("Size rank")}</th><th scope="col"><span class="sr-only">${t("Show")}</span></th></tr></thead>`;
    const rowHtml = (c, i, latest) => {
      const when = c.days > 1 ? `${FMT.date(c.start)} – ${FMT.date(c.end)}` : FMT.date(c.start);
      return `<tr class="${latest && i === 0 ? "latest" : ""}"><td>${when}${c.provisional ? '<span class="tag">provisional</span>' : ""}</td>` +
        `<td class="num">${c.days}</td><td class="num">${FMT.int(c.hotspots)}</td><td class="num">${FMT.int(c.fire_power_mw)}</td>` +
        `<td class="num">${FMT.int(c.rank)} ${ES ? "de" : "of"} ${FMT.int(c.of)}</td>` +
        `<td><button type="button" class="btn btn-small" data-fire="${latest ? "l" : "g"}${i}" aria-label="${ES ? `Ver el incendio del ${when} en el mapa` : `Show the fire of ${when} on the map`}">${t("Show")}</button></td></tr>`;
    };
    $("fires-latest").innerHTML = head + "<tbody>" + j.latest.map((c, i) => rowHtml(c, i, true)).join("") + "</tbody>";
    $("fires-largest").innerHTML = head + "<tbody>" + j.largest.map((c, i) => rowHtml(c, i, false)).join("") + "</tbody>";
    document.querySelectorAll("[data-fire]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.fire, c = (k[0] === "l" ? j.latest : j.largest)[+k.slice(1)];
      setDates(c.start, c.end);
      runSummaryOnly();
      MAP.highlight(c.bbox);
      document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }));
  }

  // ---------------------------------------------------------------- unusual right now
  async function loadUnusual() {
    let u;
    try { u = await API.unusual(); } catch (_) { return; }
    if (!u.tiles.length) return;
    const fmtDeg = (v, pos, neg) => `${Math.abs(v).toFixed(1)}°${v >= 0 ? pos : neg}`;
    const mon = FMT.MON[+u.month.slice(5) - 1];
    $("unusual-title").textContent = ES ? `Inusual ahora mismo (1–${u.days_so_far} ${mon})` : `Unusual right now (${mon} 1–${u.days_so_far})`;
    $("unusual-hint").textContent = ES
      ? `Cuadros de 1° donde este mes, hasta ahora, llega al menos a ${String(u.min_pct / 100).replace(".", ",")}× la mediana 2003–2022 de los mismos días, ` +
        `con ${u.min_hotspots}+ focos${u.provisional ? "; datos provisionales casi en tiempo real" : ""}. Cumplen ${u.tiles_total} cuadros; los mayores excesos:`
      : `1° squares where this month so far is at least ${u.min_pct / 100}× the 2003–2022 median for the same days, ` +
        `with ${u.min_hotspots}+ hotspots${u.provisional ? "; provisional near-real-time data" : ""}. ${u.tiles_total} squares qualify; the biggest excesses:`;
    const box = $("unusual-list");
    box.innerHTML = "";
    u.tiles.slice(0, 5).forEach((t) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "preset";
      const where = `${t.region_name}, ${fmtDeg(t.lat, "N", "S")} ${fmtDeg(t.lon, "E", "W")}`;
      b.innerHTML = "<strong></strong><span></span>";
      b.querySelector("strong").textContent = where;
      b.querySelector("span").textContent = ES
        ? `${FMT.int(t.value)} focos frente a ${FMT.int(t.median)} lo típico (${FMT.pct(t.pct_of_median)}${t.pct_of_median >= 1000 ? " lo normal" : " de lo normal"})`
        : `${FMT.int(t.value)} hotspots vs a typical ${FMT.int(t.median)} (${FMT.pct(t.pct_of_median)}${t.pct_of_median >= 1000 ? " normal" : " of normal"})`;
      b.addEventListener("click", () => {
        const area = { type: "bbox", bbox: t.bbox };
        setDates(`${u.month}-01`, u.as_of);
        selectTab("now");
        MAP.show(area);
        setArea(area, `Unusual now: ${where}`);
      });
      box.appendChild(b);
    });
    $("unusual").hidden = false;
  }

  // ---------------------------------------------------------------- compare two periods
  function defaultCompare() {               // the same dates one year earlier
    if (!state.start || !state.end) return;
    const back = (d) => `${+d.slice(0, 4) - 1}${d.slice(4)}`.replace("-02-29", "-02-28");
    $("cmp-start").value = back(state.start);
    $("cmp-end").value = back(state.end);
    $("compare-table").hidden = true;
  }
  async function runCompare() {
    const s2 = $("cmp-start").value, e2 = $("cmp-end").value;
    if (!s2 || !e2) return;
    busy(true);
    try {
      const [a, b] = await Promise.all([API.summary(body()), API.summary(body({ start: s2, end: e2 }))]);
      const col = (x) => ({
        dates: `${FMT.date(x.range.start)} – ${FMT.date(x.range.end)}`,
        total: FMT.int(x.key_figures.total_hotspots),
        pct: FMT.pct(x.key_figures.pct_of_median),
        month: FMT.monthLabel(x.key_figures.busiest_month),
        missing: String(x.missing_days),
      });
      const A = col(a), B = col(b);
      const ratio = b.key_figures.total_hotspots > 0 ? a.key_figures.total_hotspots / b.key_figures.total_hotspots : null;
      const rows = [[t("Dates"), A.dates, B.dates], [`Total (${units()})`, A.total, B.total], [t("vs normal"), A.pct, B.pct],
                    [t("Busiest month"), A.month, B.month], [t("Days with no data"), A.missing, B.missing]];
      const ratioText = ratio == null ? "" : ES
        ? (ratio >= 1 ? `${ratio.toFixed(1).replace(".", ",")} veces más` : `${Math.round(ratio * 100)}% del otro`)
        : (ratio >= 1 ? `${ratio.toFixed(1)}× as many` : `${Math.round(ratio * 100)}% as many`);
      const tbl = $("compare-table");
      tbl.innerHTML = `<caption class="sr-only">${ES ? "Sus fechas comparadas con otro período" : "Your dates compared with another period"}</caption>` +
        `<thead><tr><th scope="col"></th><th scope="col">${t("Your dates")}</th><th scope="col">${t("Other period")}</th></tr></thead><tbody>` +
        rows.map(([k, x, y]) => `<tr><th scope="row">${k}</th><td>${x}</td><td>${y}</td></tr>`).join("") +
        (ratio != null ? `<tr><th scope="row">${ES ? "Sus fechas vs el otro" : "Your dates vs other"}</th><td colspan="2">${ratioText}</td></tr>` : "") +
        "</tbody>";
      tbl.hidden = false;
    } catch (e) { failed(e); } finally { busy(false); }
  }

  // ---------------------------------------------------------------- choosing an area
  function setArea(area, label, presetIndex = null) {
    state.area = area;
    state.areaLabel = label;
    state.presetIndex = presetIndex;
    // on a phone the results sit below a long settings panel: jump to them after a choice
    if (state.ready && window.innerWidth < 980) setTimeout(() => $("results").scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    document.querySelectorAll("#preset-buttons .preset").forEach((b, i) => b.setAttribute("aria-pressed", String(i === presetIndex)));
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
    // redraw after the browser has laid out the tab just shown (a chart made while it was hidden is blank)
    requestAnimationFrame(() => Object.values(CHARTS.charts).forEach((c) => { c.resize(); c.update("none"); }));
    if (name === "fires") loadFires();
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

    // fire on the map
    document.querySelectorAll('input[name="mapview"]').forEach((r) => r.addEventListener("change", () => {
      state.mapview = r.value;
      refreshMap();
    }));
    $("map-month").addEventListener("input", debounce(() => { stopPlay(); refreshMap(); }, 120));
    $("map-play").addEventListener("click", togglePlay);
    $("map-speed").addEventListener("click", cycleSpeed);

    $("compare-form").addEventListener("submit", (e) => { e.preventDefault(); runCompare(); });

    // shareable link
    $("copy-link").addEventListener("click", async () => {
      writeHash();
      const btn = $("copy-link");
      try { await navigator.clipboard.writeText(location.href); btn.textContent = t("Link copied"); }
      catch (_) { window.prompt("Copy this link:", location.href); }
      setTimeout(() => { btn.textContent = t("Copy link"); }, 1800);
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
    btn.textContent = t("Preparing…");
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
      loadUnusual();
      setTimeout(() => { state.ready = true; }, 0);   // later area choices are the user's
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
