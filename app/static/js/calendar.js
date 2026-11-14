// calendar.js: the burning calendar (month x year heatmap) and the day-by-day calendars, in D3.
// Each SVG carries its own title and legend, so a PNG download stands on its own.
const CAL = (() => {
  const FONT = "Inter, system-ui, Segoe UI, sans-serif";
  const NS = "http://www.w3.org/2000/svg";

  function hatchDefs(svg, id) {
    const p = svg.append("defs").append("pattern").attr("id", id).attr("patternUnits", "userSpaceOnUse")
      .attr("width", 5).attr("height", 5).attr("patternTransform", "rotate(45)");
    p.append("rect").attr("width", 5).attr("height", 5).attr("fill", "none");
    p.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5)
      .attr("stroke", "#222").attr("stroke-width", 1.4).attr("stroke-opacity", 0.75);
  }

  let tip;
  function tooltip(html, ev) {
    if (!tip) { tip = document.createElement("div"); tip.className = "tooltip"; document.body.appendChild(tip); }
    if (!html) { tip.hidden = true; return; }
    tip.innerHTML = html; tip.hidden = false;
    const x = Math.min(ev.clientX + 12, window.innerWidth - 270);
    tip.style.left = `${x}px`; tip.style.top = `${ev.clientY + 14}px`;
  }

  function describe(c, units) {
    if (c.missing) return "no satellite data";
    let s = `${FMT.int(c.value)} ${units}`;
    if (c.median != null) s += `, normal ${FMT.int(c.median)}`;
    if (c.pct_of_median != null) s += ` (${FMT.pct(c.pct_of_median)}${c.pct_of_median >= 1000 ? " normal" : " of normal"})`;
    if (c.provisional) s += ", provisional";
    return s;
  }

  // ---- legends drawn inside the SVG ---------------------------------------------------------
  function legendCounts(g, x, y, w, scale, max, lo, units) {
    const id = "grad-" + Math.random().toString(36).slice(2);
    const grad = g.append("defs").append("linearGradient").attr("id", id);
    d3.range(0, 1.0001, 0.1).forEach((t) => grad.append("stop").attr("offset", `${t * 100}%`)
      .attr("stop-color", scale(FMT.countAt(t, max, lo))));   // log scale: even steps in log(1+count)
    g.append("rect").attr("x", x).attr("y", y).attr("width", w).attr("height", 10).attr("fill", `url(#${id})`);
    // ticks at 0, round powers of ten below the max, and the max itself
    const ticks = [];
    [Math.round(lo), ...[10, 100, 1000, 10000, 100000].filter((v) => v > lo && v < max), Math.round(max)]
      .forEach((v, i, all) => {        // keep labels at least 15% of the bar apart
        const pos = FMT.countPos(v, max, lo);
        const last = ticks.length ? FMT.countPos(ticks[ticks.length - 1], max, lo) : -1;
        const isMax = i === all.length - 1;
        if (pos - last >= 0.15) ticks.push(v);
        else if (isMax) ticks[ticks.length - 1] = v;     // the max label wins over a close tick
      });
    ticks.forEach((v, i) => {
      const tx = x + w * FMT.countPos(v, max, lo);
      g.append("text").attr("x", tx).attr("y", y + 23)
        .attr("text-anchor", i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle").text(FMT.int(v));
    });
    g.append("text").attr("x", x + w + 10).attr("y", y + 9).text(units);
  }
  function legendAnomaly(g, x, y, w, label = "vs the median for that month") {
    const id = "grad-" + Math.random().toString(36).slice(2);
    const grad = g.append("defs").append("linearGradient").attr("id", id);
    d3.range(0, 1.0001, 0.1).forEach((t) => grad.append("stop").attr("offset", `${t * 100}%`)
      .attr("stop-color", d3.interpolatePuOr(t)));   // left: purple (less), right: orange (more)
    g.append("rect").attr("x", x).attr("y", y).attr("width", w).attr("height", 10).attr("fill", `url(#${id})`);
    [["10× less", 0], ["normal", 0.5], ["10× more", 1]].forEach(([t, f]) =>
      g.append("text").attr("x", x + w * f).attr("y", y + 23).attr("text-anchor", f === 0 ? "start" : f === 1 ? "end" : "middle").text(t));
    g.append("text").attr("x", x + w + 10).attr("y", y + 9).text(label);
  }
  function legendKeys(g, x, y, hatchId) {
    g.append("rect").attr("x", x).attr("y", y).attr("width", 12).attr("height", 12).attr("fill", FMT.MISSING);
    g.append("text").attr("x", x + 17).attr("y", y + 10).text("no data");
    g.append("rect").attr("x", x + 80).attr("y", y).attr("width", 12).attr("height", 12).attr("fill", "#fff").attr("stroke", "#888");
    g.append("rect").attr("x", x + 80).attr("y", y).attr("width", 12).attr("height", 12).attr("fill", `url(#${hatchId})`);
    g.append("text").attr("x", x + 97).attr("y", y + 10).text("provisional");
  }

  // ---- month x year burning calendar --------------------------------------------------------
  // cells: /api/calendar month cells for the whole record. opts: view, units, range [start,end],
  // title, onPick(period)
  function months(container, cells, opts) {
    container.innerHTML = "";
    if (!cells.length) { container.textContent = "No data for this area."; return; }
    const years = [...new Set(cells.map((c) => +c.period.slice(0, 4)))].sort((a, b) => a - b);
    const byKey = new Map(cells.map((c) => [c.period, c]));
    const cw = 27, ch = 19, gap = 2, left = 40, top = 52;
    const width = left + years.length * cw + 10, gridH = 12 * ch;
    const height = top + gridH + 64;
    const max = d3.max(cells, (c) => (c.missing ? 0 : c.value || 0)) || 1;
    // start the color ramp at the quietest ~5% of months (not 0) so normal seasons stay visible
    const positive = cells.filter((c) => !c.missing && c.value > 0).map((c) => c.value).sort(d3.ascending);
    const lo = positive.length ? d3.quantileSorted(positive, 0.05) : 0;
    const scale = FMT.countScale(max, lo);
    const hatchId = "hatch-" + Math.random().toString(36).slice(2);

    const svg = d3.select(container).append("svg").attr("id", "calendar-svg")
      .attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("xmlns", NS)
      .attr("font-family", FONT).attr("font-size", 10).attr("fill", FMT.ink)
      .attr("role", "group").attr("aria-label", `Burning calendar: ${opts.units} per month, ${years[0]} to ${years[years.length - 1]}`);
    hatchDefs(svg, hatchId);
    svg.append("rect").attr("width", width).attr("height", height).attr("fill", "#fff");
    svg.append("text").attr("x", left).attr("y", 16).attr("font-size", 13).attr("font-weight", 600).text(opts.title);

    // year labels
    years.forEach((y, i) => svg.append("text").attr("x", left + i * cw + cw / 2 - 1).attr("y", top - 6)
      .attr("text-anchor", "middle").attr("font-size", 9.5).text(`'${String(y).slice(2)}`));
    svg.append("text").attr("x", left).attr("y", 33).attr("font-size", 10).attr("fill", "#5b6168").text("year →");
    FMT.MON.forEach((m, i) => svg.append("text").attr("x", left - 6).attr("y", top + i * ch + ch / 2 + 3.5)
      .attr("text-anchor", "end").text(m));

    const [rs, re] = (opts.range || []).map((d) => d && d.slice(0, 7));
    const grid = svg.append("g");
    years.forEach((y, xi) => {
      for (let m = 1; m <= 12; m++) {
        const key = `${y}-${String(m).padStart(2, "0")}`;
        const c = byKey.get(key);
        if (!c) continue;
        const x = left + xi * cw, yy = top + (m - 1) * ch;
        const fill = c.missing ? FMT.MISSING
          : opts.view === "anomaly" ? (FMT.anomalyColor(c.value, c.median) || FMT.MISSING) : scale(c.value || 0);
        const g = grid.append("g").attr("class", "cal-cell").attr("tabindex", 0).attr("role", "button")
          .attr("data-x", xi).attr("data-y", m - 1).attr("data-period", key)
          .attr("aria-label", `${FMT.MONTHS[m - 1]} ${y}: ${describe(c, opts.units)}. Press Enter for days.`);
        g.append("rect").attr("class", "cell").attr("x", x).attr("y", yy).attr("width", cw - gap).attr("height", ch - gap)
          .attr("rx", 2).attr("fill", fill);
        if (c.provisional && !c.missing) g.append("rect").attr("x", x).attr("y", yy).attr("width", cw - gap)
          .attr("height", ch - gap).attr("rx", 2).attr("fill", `url(#${hatchId})`).attr("pointer-events", "none");
        g.on("click", () => opts.onPick(key))
          .on("keydown", (ev) => onKey(ev, grid, key, opts))
          .on("mousemove", (ev) => tooltip(`<b>${FMT.MONTHS[m - 1]} ${y}</b><br>${describe(c, opts.units)}`, ev))
          .on("mouseleave", () => tooltip(null));
      }
    });
    // outline the user's date range
    if (rs && re) {
      years.forEach((y, xi) => {
        for (let m = 1; m <= 12; m++) {
          const key = `${y}-${String(m).padStart(2, "0")}`;
          if (!(key >= rs && key <= re && byKey.has(key))) continue;
          // black + white double outline: visible on dark and light squares alike
          [["#111", 3], ["#fff", 1.2]].forEach(([color, sw]) => grid.append("rect")
            .attr("x", left + xi * cw - 0.5).attr("y", top + (m - 1) * ch - 0.5)
            .attr("width", cw - gap + 1).attr("height", ch - gap + 1).attr("rx", 2)
            .attr("fill", "none").attr("stroke", color).attr("stroke-width", sw).attr("pointer-events", "none"));
        }
      });
    }

    const lg = svg.append("g").attr("font-size", 10.5);
    const ly = top + gridH + 18;
    if (opts.view === "anomaly") legendAnomaly(lg, left, ly, 220);
    else legendCounts(lg, left, ly, 220, scale, max, lo, opts.units + " per month");
    legendKeys(lg, left + 520 > width - 180 ? left : width - 190, ly + (left + 520 > width - 180 ? 34 : 0), hatchId);
    if (left + 520 > width - 180) svg.attr("viewBox", `0 0 ${width} ${height + 26}`);
  }

  function onKey(ev, grid, key, opts) {
    const node = ev.currentTarget;
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); opts.onPick(key); return; }
    const dx = { ArrowLeft: -1, ArrowRight: 1 }[ev.key] || 0;
    const dy = { ArrowUp: -1, ArrowDown: 1 }[ev.key] || 0;
    if (!dx && !dy) return;
    ev.preventDefault();
    const x = +node.dataset.x + dx, y = +node.dataset.y + dy;
    const next = grid.node().querySelector(`.cal-cell[data-x="${x}"][data-y="${y}"]`);
    if (next) next.focus();
  }

  // ---- day-by-day calendar for one month (or a few weeks) -----------------------------------
  // cells: /api/calendar day cells. Colors show each day vs the normal for that time of year.
  function days(container, cells, opts) {
    container.innerHTML = "";
    if (!cells.length) { container.textContent = "No days to show."; return; }
    const cw = 64, ch = 46, gap = 4, left = 10, top = 54;
    const first = new Date(cells[0].period + "T00:00:00Z");
    const offset = (first.getUTCDay() + 6) % 7;            // Monday = 0
    const rows = Math.ceil((offset + cells.length) / 7);
    const width = left + 7 * cw + 10, height = top + rows * ch + 56;
    const hatchId = "hatch-" + Math.random().toString(36).slice(2);
    const svg = d3.select(container).append("svg").attr("id", opts.id).attr("xmlns", NS)
      .attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("font-family", FONT)
      .attr("font-size", 11).attr("fill", FMT.ink).attr("role", "group").attr("aria-label", opts.title);
    hatchDefs(svg, hatchId);
    svg.append("rect").attr("width", width).attr("height", height).attr("fill", "#fff");
    svg.append("text").attr("x", left).attr("y", 18).attr("font-size", 13).attr("font-weight", 600).text(opts.title);
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((d, i) => svg.append("text")
      .attr("x", left + i * cw + (cw - gap) / 2).attr("y", top - 8).attr("text-anchor", "middle").attr("fill", "#5b6168").text(d));
    cells.forEach((c, i) => {
      const k = offset + i, x = left + (k % 7) * cw, y = top + Math.floor(k / 7) * ch;
      const fill = c.missing ? FMT.MISSING : (FMT.anomalyColor(c.value, c.median) || FMT.MISSING);
      const day = +c.period.slice(8, 10);
      const g = svg.append("g").attr("tabindex", 0).attr("role", "img")
        .attr("aria-label", `${FMT.date(c.period)}: ${describe(c, opts.units)}`);
      g.append("rect").attr("x", x).attr("y", y).attr("width", cw - gap).attr("height", ch - gap).attr("rx", 4).attr("fill", fill);
      if (c.provisional && !c.missing) g.append("rect").attr("x", x).attr("y", y).attr("width", cw - gap)
        .attr("height", ch - gap).attr("rx", 4).attr("fill", `url(#${hatchId})`).attr("opacity", 0.5);
      const tc = FMT.textOn(fill);
      g.append("text").attr("x", x + 5).attr("y", y + 13).attr("font-size", 10).attr("fill", tc).text(day);
      g.append("text").attr("x", x + (cw - gap) / 2).attr("y", y + 32).attr("text-anchor", "middle")
        .attr("font-size", 13).attr("font-weight", 600).attr("fill", tc).text(c.missing ? "–" : FMT.int(c.value));
      g.on("mousemove", (ev) => tooltip(`<b>${FMT.date(c.period)}</b><br>${describe(c, opts.units)}`, ev))
        .on("mouseleave", () => tooltip(null));
    });
    const lg = svg.append("g").attr("font-size", 10.5);
    legendAnomaly(lg, left, top + rows * ch + 12, 180, "vs normal for that time of year");
    legendKeys(lg, left, top + rows * ch + 40, hatchId);
  }

  return { months, days };
})();
