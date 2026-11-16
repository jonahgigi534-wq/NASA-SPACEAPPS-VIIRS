// charts.js: Chart.js charts (patterns, now vs history, long-term record) + PNG export.
const CHARTS = (() => {
  const ES = typeof I18N !== "undefined" && I18N.es;
  const L = (en, es) => (ES ? es : en);
  const C = {
    harmonized: "#1d5fa8",   // blue
    viirs: "#e8590c",        // orange (blue/orange is safe for common color blindness)
    modis: "#111111",
    bar: "#8fa3b8",
    hot: "#c2410c",
    season: "rgba(232, 89, 12, 0.10)",
    grid: "#ececec",
  };
  Chart.defaults.font.family = "Inter, system-ui, Segoe UI, sans-serif";
  Chart.defaults.color = "#3a3f45";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 };

  // white background so downloaded PNGs aren't transparent
  const whiteBg = { id: "whiteBg", beforeDraw(chart) {
    const { ctx, width, height } = chart; ctx.save(); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, width, height); ctx.restore();
  } };
  // shade a band of category indexes (fire season), may wrap past December
  const band = { id: "band", beforeDatasetsDraw(chart, _a, o) {
    if (!o || !o.ranges) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save(); ctx.fillStyle = C.season;
    o.ranges.forEach(([i0, i1]) => {
      const half = (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2;
      const x0 = x.getPixelForValue(i0) - half, x1 = x.getPixelForValue(i1) + half;
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    });
    if (o.label) { ctx.fillStyle = "#9a3412"; ctx.font = "600 11px Inter, sans-serif";
      ctx.fillText(o.label, x.getPixelForValue(o.ranges[0][0]) - (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2 + 4, a.top + 12); }
    ctx.restore();
  } };
  // vertical lines on a time axis (sensor switches)
  const vlines = { id: "vlines", afterDatasetsDraw(chart, _a, o) {
    if (!o || !o.lines) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save(); ctx.strokeStyle = "#555"; ctx.setLineDash([4, 4]); ctx.fillStyle = "#333"; ctx.font = "11px Inter, sans-serif";
    o.lines.forEach(({ index, label }, i) => {
      const px = x.getPixelForValue(index);
      if (px < a.left || px > a.right) return;
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillText(label, px + 4, a.top + 12 + i * 14);     // staggered so labels never overlap
    });
    ctx.restore();
  } };
  Chart.register(whiteBg, band, vlines);

  const charts = {};
  // A chart made inside a hidden tab is drawn at zero size. Watch each chart's box and redraw the
  // chart whenever the box gets a size the canvas doesn't have yet (the tab was opened).
  const boxWatch = new ResizeObserver((entries) => entries.forEach(({ target }) => {
    const canvas = target.querySelector("canvas"), c = canvas && Chart.getChart(canvas);
    if (!c || target.clientWidth === 0) return;
    if (canvas.clientWidth !== target.clientWidth || canvas.clientHeight === 0) { c.resize(); c.update("none"); }
  }));
  function make(id, config) {
    if (charts[id]) charts[id].destroy();
    const canvas = document.getElementById(id);
    charts[id] = new Chart(canvas, config);
    boxWatch.observe(canvas.parentElement);
    srTable(id);
    return charts[id];
  }

  // A hidden data table after each chart, so screen-reader users get the numbers too.
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function srTable(id) {
    const ch = charts[id], canvas = document.getElementById(id);
    if (!ch.data.labels || !ch.data.labels.length) return;     // scatter charts: their data is in HTML tables
    let t = document.getElementById(`${id}-table`);
    if (!t) {
      // the wrapper is visually hidden (a table itself ignores the 1px width and would widen the page)
      const wrap = document.createElement("div");
      wrap.className = "sr-only";
      t = document.createElement("table");
      t.id = `${id}-table`;
      wrap.appendChild(t);
      canvas.parentElement.after(wrap);
    }
    const ds = ch.data.datasets.filter((d) => d.data.some((v) => v != null));
    const title = (ch.options.plugins.title && ch.options.plugins.title.text) || canvas.getAttribute("aria-label");
    const cell = (v) => (v == null ? "no data" : Math.round(v).toLocaleString("en-US"));
    t.innerHTML = `<caption>${esc(title)} ${L("(data table)", "(tabla de datos)")}</caption><thead><tr><th scope="col">${L("Period", "Período")}</th>` +
      ds.map((d) => `<th scope="col">${esc(d.label || L("value", "valor"))}</th>`).join("") + "</tr></thead><tbody>" +
      ch.data.labels.map((l, i) => `<tr><th scope="row">${esc(l)}</th>${ds.map((d) => `<td>${cell(d.data[i])}</td>`).join("")}</tr>`).join("") +
      "</tbody>";
  }
  const axisTitle = (text) => ({ display: true, text, font: { size: 12 } });
  const titlePlugin = (text) => ({ display: true, text, align: "start", font: { size: 13, weight: "600" }, padding: { bottom: 8 } });

  // month-of-year index (0..11) ranges from fire_season "MM-DD" start/end
  function seasonRanges(fs) {
    if (!fs) return [];
    const s = +fs.start.slice(0, 2) - 1, e = +fs.end.slice(0, 2) - 1;
    return s <= e ? [[s, e]] : [[s, 11], [0, e]];
  }

  function months(p, units) {
    const hot = new Set(p.high_risk_months);
    const data = p.monthly_median.map((m) => m.median);
    make("chart-months", {
      type: "bar",
      data: { labels: FMT.MON, datasets: [{
        label: L(`Typical (median) ${units} per month`, `${units} típicos (mediana) por mes`), data,
        backgroundColor: p.monthly_median.map((m) => hot.has(m.month) ? C.hot : C.bar), borderRadius: 3 }] },
      options: {
        plugins: {
          title: titlePlugin(L(`Typical ${units} per month (median of the normal years)`, `${units} típicos por mes (mediana de los años normales)`)),
          legend: { display: false },
          band: { ranges: seasonRanges(p.fire_season), label: p.fire_season ? L("fire season", "temporada de incendios") : "" },
          tooltip: { callbacks: { label: (c) => {
            const m = p.monthly_median[c.dataIndex];
            return [`median ${FMT.int(m.median)}, mean ${FMT.int(m.mean)}`, hot.has(m.month) ? "high-risk month" : ""].filter(Boolean);
          } } },
        },
        scales: { y: { beginAtZero: true, title: axisTitle(units), grid: { color: C.grid } }, x: { grid: { display: false } } },
      },
    });
  }

  function years(p, units) {
    const rows = [...p.years_ranked].sort((a, b) => a.year - b.year);
    const top = new Set(p.years_ranked.slice(0, 3).map((r) => r.year));
    make("chart-years", {
      type: "bar",
      data: { labels: rows.map((r) => r.year), datasets: [{
        label: L(`${units} per year`, `${units} por año`), data: rows.map((r) => r.total),
        backgroundColor: rows.map((r) => top.has(r.year) ? C.hot : C.bar), borderRadius: 2 }] },
      options: {
        plugins: { title: titlePlugin(L(`${units} per year (busiest 3 highlighted)`, `${units} por año (los 3 más activos resaltados)`)), legend: { display: false },
          tooltip: { callbacks: { label: (c) => {
            const r = rows[c.dataIndex]; return `${FMT.int(r.total)} ${units} · rank ${r.rank} of ${rows.length}`;
          } } } },
        scales: { y: { beginAtZero: true, title: axisTitle(units), grid: { color: C.grid } },
                  x: { grid: { display: false }, ticks: { autoSkip: true, maxRotation: 0 } } },
      },
    });
  }

  function now(cur, units) {
    make("chart-now", {
      type: "bar",
      data: { labels: ES ? ["Este mes hasta ahora", "Lo típico para estos días"] : ["This month so far", "Typical for these days"], datasets: [{
        data: [cur.value_so_far, cur.median_same_days], backgroundColor: [C.hot, C.bar], borderRadius: 4 }] },
      options: {
        indexAxis: "y",
        plugins: { title: titlePlugin(`${FMT.monthLabel(cur.month)}, ${L("days", "días")} 1–${cur.days_so_far}: ${units}`), legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${FMT.int(c.raw)} ${units}` } } },
        scales: { x: { beginAtZero: true, title: axisTitle(units), grid: { color: C.grid } }, y: { grid: { display: false } } },
      },
    });
  }

  function longterm(ts, mode, yTitle = "hotspots per month") {
    const labels = ts.series.map((r) => r.month);
    const idx = (iso) => labels.indexOf(iso.slice(0, 7));
    // order: lower is drawn on top. The MODIS reference goes on top as a thin dashed line, because
    // the harmonized line follows it closely (and equals it before 2012) and would hide it.
    const ds = (key, label, color, dash, order) => ({
      label, data: ts.series.map((r) => r[key]), borderColor: color, backgroundColor: color,
      borderWidth: mode === key ? 2.6 : key === "modis_only" ? 1.8 : 1.3, borderDash: dash,
      pointRadius: 0, spanGaps: false, tension: 0, order,
    });
    make("chart-longterm", {
      type: "line",
      data: { labels, datasets: [
        ds("viirs_raw", L("Raw VIIRS (not harmonized)", "VIIRS sin ajustar (no armonizado)"), C.viirs, undefined, 2),
        ds("modis_only", L("MODIS only (reference)", "Solo MODIS (referencia)"), C.modis, [5, 3], 0),
        ds("harmonized", L("Harmonized (MODIS scale)", "Armonizado (escala MODIS)"), C.harmonized, undefined, 1),
      ].filter((d) => d.data.some((v) => v != null)) },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: {
          title: titlePlugin(`${yTitle[0].toUpperCase()}${yTitle.slice(1)}, 2001 → ${L("today", "hoy")}`),
          legend: { position: "top", align: "start", labels: { boxWidth: 18, sort: (a, b) => a.datasetIndex - b.datasetIndex } },
          vlines: { lines: ts.sensor_switches.map((s) => ({ index: idx(s.date), label: s.label })).filter((l) => l.index >= 0) },
          tooltip: { callbacks: { title: (it) => FMT.monthLabel(it[0].label),
            label: (c) => `${c.dataset.label}: ${c.raw == null ? L("no data", "sin datos") : FMT.int(c.raw)}` } },
        },
        scales: {
          x: { ticks: { callback: (v, i) => labels[i].endsWith("-01") && +labels[i].slice(0, 4) % 2 === 1 ? labels[i].slice(0, 4) : "",
                        autoSkip: false, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, title: axisTitle(yTitle), grid: { color: C.grid } },
        },
      },
    });
  }

  function fires(j, units) {
    const all = j.all.map(([d, h, days]) => ({ x: Date.parse(d), y: Math.max(h, 0.5), d, days }));
    const last = j.latest[0];
    const latest = last ? [{ x: Date.parse(last.start), y: last.hotspots, d: last.start, days: last.days }] : [];
    make("chart-fires", {
      type: "scatter",
      data: { datasets: [
        { label: L("Most recent fire cluster", "Grupo de incendios más reciente"), data: latest, backgroundColor: C.hot, borderColor: "#7c2d12", borderWidth: 1.5, pointRadius: 7, order: 0 },
        { label: L("Every earlier fire cluster", "Todos los grupos anteriores"), data: all, backgroundColor: "rgba(29, 95, 168, 0.35)", pointRadius: 2.5, order: 1 },
      ] },
      options: {
        plugins: {
          title: titlePlugin(L(`Fire clusters by start date and size (${units}, log scale)`, `Grupos de incendios por fecha de inicio y tamaño (${units}, escala log)`)),
          legend: { position: "top", align: "start", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: (c) => `${FMT.date(c.raw.d)}: ${FMT.int(c.raw.y)} ${units}, ${c.raw.days} ${ES ? (c.raw.days === 1 ? "día" : "días") : (c.raw.days === 1 ? "day" : "days")}` } },
        },
        scales: {
          x: { type: "linear", min: Date.UTC(2001, 0, 1), max: Date.UTC(new Date().getUTCFullYear() + 1, 0, 1),
               ticks: { callback: (v) => new Date(v).getUTCFullYear(), maxRotation: 0, autoSkip: true }, grid: { display: false } },
          y: { type: "logarithmic", title: axisTitle(L(`${units} per cluster`, `${units} por grupo`)), grid: { color: C.grid },
               ticks: { callback: (v) => ([1, 10, 100, 1000, 10000, 100000].includes(v) ? FMT.int(v) : "") } },
        },
      },
    });
  }

  // ---- PNG export ---------------------------------------------------------------------------
  function downloadCanvas(id, name) {
    const ch = charts[id];
    if (!ch) return;
    const a = document.createElement("a");
    a.href = ch.toBase64Image("image/png", 1);
    a.download = name;
    a.click();
  }
  function downloadSvg(svgEl, name, scale = 2) {
    const xml = new XMLSerializer().serializeToString(svgEl);
    const vb = svgEl.viewBox.baseVal;
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = vb.width * scale; canvas.height = vb.height * scale;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => API.saveBlob(b, name), "image/png");
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  return { months, years, now, longterm, fires, downloadCanvas, downloadSvg, charts };
})();
