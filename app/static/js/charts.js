// charts.js: Chart.js charts (patterns, now vs history, long-term record) + PNG export.
const CHARTS = (() => {
  const C = {
    harmonized: "#1d5fa8",   // blue
    viirs: "#e8590c",        // orange (blue/orange is safe for common color blindness)
    modis: "#3d3d3d",
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
  function make(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
    return charts[id];
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
        label: `Typical (median) ${units} per month`, data,
        backgroundColor: p.monthly_median.map((m) => hot.has(m.month) ? C.hot : C.bar), borderRadius: 3 }] },
      options: {
        plugins: {
          title: titlePlugin(`Typical ${units} per month (median of the normal years)`),
          legend: { display: false },
          band: { ranges: seasonRanges(p.fire_season), label: p.fire_season ? "fire season" : "" },
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
        label: `${units} per year`, data: rows.map((r) => r.total),
        backgroundColor: rows.map((r) => top.has(r.year) ? C.hot : C.bar), borderRadius: 2 }] },
      options: {
        plugins: { title: titlePlugin(`${units} per year (busiest 3 highlighted)`), legend: { display: false },
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
      data: { labels: ["This month so far", "Typical for these days"], datasets: [{
        data: [cur.value_so_far, cur.median_same_days], backgroundColor: [C.hot, C.bar], borderRadius: 4 }] },
      options: {
        indexAxis: "y",
        plugins: { title: titlePlugin(`${FMT.monthLabel(cur.month)}, days 1–${cur.days_so_far}: ${units}`), legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${FMT.int(c.raw)} ${units}` } } },
        scales: { x: { beginAtZero: true, title: axisTitle(units), grid: { color: C.grid } }, y: { grid: { display: false } } },
      },
    });
  }

  function longterm(ts, mode) {
    const labels = ts.series.map((r) => r.month);
    const idx = (iso) => labels.indexOf(iso.slice(0, 7));
    const ds = (key, label, color, dash) => ({
      label, data: ts.series.map((r) => r[key]), borderColor: color, backgroundColor: color,
      borderWidth: mode === key ? 2.6 : 1.3, borderDash: dash, pointRadius: 0, spanGaps: false, tension: 0,
    });
    make("chart-longterm", {
      type: "line",
      data: { labels, datasets: [
        ds("viirs_raw", "Raw VIIRS (not harmonized)", C.viirs),
        ds("modis_only", "MODIS only (reference)", C.modis, [3, 3]),
        ds("harmonized", "Harmonized (MODIS scale)", C.harmonized),
      ] },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: {
          title: titlePlugin("Hotspots per month, 2001 → today"),
          legend: { position: "top", align: "start", labels: { boxWidth: 18 } },
          vlines: { lines: ts.sensor_switches.map((s) => ({ index: idx(s.date), label: s.label })).filter((l) => l.index >= 0) },
          tooltip: { callbacks: { title: (it) => FMT.monthLabel(it[0].label),
            label: (c) => `${c.dataset.label}: ${c.raw == null ? "no data" : FMT.int(c.raw)}` } },
        },
        scales: {
          x: { ticks: { callback: (v, i) => labels[i].endsWith("-01") && +labels[i].slice(0, 4) % 2 === 1 ? labels[i].slice(0, 4) : "",
                        autoSkip: false, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, title: axisTitle("hotspots per month"), grid: { color: C.grid } },
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

  return { months, years, now, longterm, downloadCanvas, downloadSvg, charts };
})();
