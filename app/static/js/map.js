// map.js: Leaflet map with our data regions outlined and draw tools (rectangle, polygon, circle).
// Whatever the user draws becomes an API "area" (docs/CONTRACTS.md section 4).
const MAP = (() => {
  const ES = typeof I18N !== "undefined" && I18N.es;
  let map, drawn, onArea;

  function init(regions, onAreaChosen) {
    onArea = onAreaChosen;
    // Zoom with the mouse wheel, a pinch, a double-click, the + and - keys or the buttons. The wheel
    // zooms in half steps so it feels smooth; scroll the page from the side rail or "Full analysis".
    map = L.map("map", { worldCopyJump: true, zoomControl: false, scrollWheelZoom: true, zoomSnap: 0.25,
                         zoomDelta: 0.5, wheelPxPerZoomLevel: 90, wheelDebounceTime: 20 }).setView([5, -40], 2);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    // OpenStreetMap's standard tiles: no API key, attribution required. CSS mutes them to a quiet
    // grey (.leaflet-tile-pane filter in style.css) so the fire layer is what you see.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    const bounds = [];
    regions.forEach((r) => {
      const [w, s, e, n] = r.bbox;
      const rect = L.rectangle([[s, w], [n, e]], { color: "#c2410c", weight: 1.5, dashArray: "5 4", fill: false, interactive: false });
      rect.addTo(map).bindTooltip(r.name, { permanent: false });
      bounds.push([[s, w], [n, e]]);
    });

    drawn = new L.FeatureGroup().addTo(map);
    const style = { color: "#1d5fa8", weight: 2, fillOpacity: 0.04 };
    map.addControl(new L.Control.Draw({
      position: "topright",
      draw: { rectangle: { shapeOptions: style }, polygon: { shapeOptions: style, allowIntersection: false },
              circle: { shapeOptions: style }, polyline: false, marker: false, circlemarker: false },
      edit: false,
    }));
    map.on(L.Draw.Event.CREATED, (e) => {
      drawn.clearLayers();
      drawn.addLayer(e.layer);
      onArea(layerToArea(e.layerType, e.layer), labelFor(e.layerType));
    });
    map.on(L.Draw.Event.DRAWSTART, () => { drawing = true; map.closePopup(); });
    map.on(L.Draw.Event.DRAWSTOP, () => { drawing = false; });
    map.on("click", cellPopup);
    return bounds;
  }

  // ---- click a square of the fire layer: a small card about that spot ----
  let drawing = false;
  const ratioWords = (v, m) => {
    if (!(m > 0)) return v > 0 ? "No fire is normal here for these dates, so any is unusual." : "No fire here, as usual.";
    const r = v / m;
    if (r >= 1.15) return `<b class="pop-hot">${r >= 10 ? Math.round(r) : r.toFixed(1)}× the normal</b> for these dates.`;
    if (r <= 0.87) return `<b class="pop-cool">${Math.round(r * 100)}% of normal</b>: quieter than usual.`;
    return "<b>About normal</b> for these dates.";
  };
  // a click zooms in on the spot first (the squares get finer as you zoom), then explains it
  const CLICK_ZOOM_STEP = 2, CLICK_ZOOM_MAX = 8;
  function cellPopup(e) {
    if (drawing || !grid || !grid.at(e.latlng)) return;
    const z = map.getZoom();
    if (z >= CLICK_ZOOM_MAX) { openCellPopup(e.latlng); return; }
    map.closePopup();
    map.once("moveend", () => openCellPopup(e.latlng));
    map.flyTo(e.latlng, Math.min(z + CLICK_ZOOM_STEP, CLICK_ZOOM_MAX), { duration: 0.8 });
  }
  function openCellPopup(latlng) {
    if (drawing || !grid) return;
    const c = grid.at(latlng);
    if (!c) return;
    const d = grid.deg, half = d / 2;
    const lat = c.lat.toFixed(2), lon = c.lon.toFixed(2);
    const box = document.createElement("div");
    box.className = "fire-pop";
    box.innerHTML =
      `<p class="pop-kicker">This ${d}° square</p>` +
      `<p class="pop-num">${FMT.int(c.value)} <span>${grid.units}</span></p>` +
      `<p>${ratioWords(c.value, c.median)}${c.median > 0 ? ` Normal is ${FMT.int(c.median)}, the median for the same dates in the baseline years.` : ""}</p>` +
      `<p class="pop-fine">Centre ${lat}°, ${lon}°. Each square adds up every satellite hotspot detected inside it in your dates.</p>` +
      `<button type="button" class="pop-btn">Look closer at this square</button>`;
    box.querySelector(".pop-btn").addEventListener("click", () => {
      map.closePopup();
      const bbox = [c.lon - half, c.lat - half, c.lon + half, c.lat + half].map((v) => +v.toFixed(4));
      drawn.clearLayers();
      drawn.addLayer(L.rectangle([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], { color: "#1d5fa8", weight: 2, fillOpacity: 0.04 }));
      onArea({ type: "bbox", bbox }, `Square at ${lat}°, ${lon}°`);
    });
    if (tip) map.closeTooltip(tip);
    L.popup({ className: "fire-popup", maxWidth: 280, minWidth: 240, offset: [0, -6], autoPanPadding: [40, 90] })
      .setLatLng(latlng).setContent(box).openOn(map);
  }

  function labelFor(type) {
    return { rectangle: "Your box", polygon: "Your polygon", circle: "Your circle" }[type] || "Your area";
  }

  function layerToArea(type, layer) {
    if (type === "circle") {
      const c = layer.getLatLng();
      return { type: "point", lat: +c.lat.toFixed(5), lon: +wrap(c.lng).toFixed(5), radius_km: +(layer.getRadius() / 1000).toFixed(2) };
    }
    if (type === "rectangle") {
      const b = layer.getBounds();
      return { type: "bbox", bbox: [wrap(b.getWest()), b.getSouth(), wrap(b.getEast()), b.getNorth()].map((v) => +v.toFixed(4)) };
    }
    const ring = layer.getLatLngs()[0].map((p) => [+wrap(p.lng).toFixed(5), +p.lat.toFixed(5)]);
    ring.push(ring[0]);
    return { type: "polygon", coordinates: [ring] };
  }
  const wrap = (lng) => ((lng + 540) % 360) - 180;

  // keep the area clear of the floating pills (top) and the timeline card (bottom)
  function fitPad() {
    const h = map.getSize().y;
    return h > 480 ? { paddingTopLeft: [40, 90], paddingBottomRight: [40, 230] } : { padding: [20, 20] };
  }

  // draw an area that came from a preset or typed coordinates
  function show(area) {
    drawn.clearLayers();
    const style = { color: "#1d5fa8", weight: 2, fillOpacity: 0.04 };
    let layer;
    if (area.type === "bbox") { const [w, s, e, n] = area.bbox; layer = L.rectangle([[s, w], [n, e]], style); }
    else if (area.type === "point") layer = L.circle([area.lat, area.lon], { ...style, radius: area.radius_km * 1000 });
    else layer = L.polygon(area.coordinates[0].map(([x, y]) => [y, x]), style);
    drawn.addLayer(layer);
    map.fitBounds(layer.getBounds(), { ...fitPad(), maxZoom: 8, animate: false });
  }

  // ---- fire on the map: a smooth radar-style layer, like the rain layer of a weather app.
  // The counts are still per square (0.1 degree, or merged when zoomed out). We paint one pixel per
  // square, blur and enlarge it, then colour each pixel from the blurred value. Hover still reads
  // the true number of the square under the pointer.
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PAD = 3;            // empty squares around the data, so the soft edge has room to fade out
  const BLUR = 0.62;        // blur radius, in squares
  const FADE_MS = 520;      // cross-fade between layers (month-by-month playback rolls)
  const MAX_ALPHA = 0.9;
  let overlay = null, legend = null, last = null, lastDeg = null, grid = null, tip = null;
  // Zoomed out, 0.1 degree squares are a pixel or two wide: merge them into bigger squares.
  function binSize(z) { return z <= 4 ? 0.5 : z < 6.5 ? 0.25 : 0.1; }
  function binned(data, deg) {
    if (deg <= data.cell_deg + 1e-9) return data.cells;
    const bins = new Map();
    data.cells.forEach((c) => {
      const la = Math.floor(c.lat / deg) * deg + deg / 2, lo = Math.floor(c.lon / deg) * deg + deg / 2;
      const k = `${la.toFixed(3)},${lo.toFixed(3)}`;
      const b = bins.get(k) || { lat: la, lon: lo, value: 0, median: 0 };
      b.value += c.value; b.median += c.median;
      bins.set(k, b);
    });
    return [...bins.values()];
  }
  function showCells(data, view, units, caption) {
    last = { data, view, units, caption };
    if (!legend) {
      map.on("zoomend", () => {          // redraw only when the square size changes with the zoom
        if (last && last.data && last.view !== "off" && Math.max(last.data.cell_deg, binSize(map.getZoom())) !== lastDeg)
          draw(last.data, last.view, last.units, last.caption);
      });
      map.on("mousemove", hover);
      map.on("mouseout", () => tip && map.closeTooltip(tip));
      legend = L.control({ position: "bottomleft" });
      legend.onAdd = () => { const d = L.DomUtil.create("div", "map-legend"); d.setAttribute("aria-hidden", "true"); return d; };
      legend.addTo(map);
    }
    draw(data, view, units, caption);
  }

  function clearOverlay() {
    const old = overlay;
    overlay = null; grid = null;
    if (tip) map.closeTooltip(tip);
    map.closePopup();
    if (!old) return;
    const el = old.getElement();
    if (el && el.animate && !REDUCED)
      el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_MS, easing: "ease-in", fill: "forwards" }).onfinish = () => old.remove();
    else old.remove();
  }

  const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
  const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const unmerc = (m) => (360 / Math.PI) * Math.atan(Math.exp(m)) - 90;
  function ramp(interp) {                  // 256 colours of a d3 colour scale, as [r, g, b]
    return d3.range(256).map((i) => { const c = d3.rgb(interp(i / 255)); return [c.r, c.g, c.b]; });
  }

  // cells: [{lat, lon, ...}] square centres; pos(cell) -> 0..1 place on the colour scale (null = skip)
  function radar(cells, deg, pos, colours, fringe) {
    let w0 = Infinity, s0 = Infinity, e0 = -Infinity, n0 = -Infinity;
    const used = cells.filter((c) => pos(c) != null);
    if (!used.length) return null;
    used.forEach((c) => { w0 = Math.min(w0, c.lon); e0 = Math.max(e0, c.lon); s0 = Math.min(s0, c.lat); n0 = Math.max(n0, c.lat); });
    const nc = Math.round((e0 - w0) / deg) + 1 + 2 * PAD, nr = Math.round((n0 - s0) / deg) + 1 + 2 * PAD;
    // one pixel per square: red = place on the colour scale, green = "there is data here"
    const small = document.createElement("canvas");
    small.width = nc; small.height = nr;
    const sctx = small.getContext("2d");
    const img = sctx.createImageData(nc, nr);
    for (let i = 3; i < img.data.length; i += 4) img.data[i] = 255;
    const index = new Map();
    used.forEach((c) => {
      const ix = Math.round((c.lon - w0) / deg), iy = Math.round((c.lat - s0) / deg);
      const o = 4 * ((nr - 1 - iy - PAD) * nc + ix + PAD);
      img.data[o] = Math.round(pos(c) * 255); img.data[o + 1] = 255;
      index.set(`${ix},${iy}`, c);
    });
    sctx.putImageData(img, 0, 0);
    // enlarge and blur
    const S = Math.max(4, Math.min(16, Math.floor(1200 / nc)));
    const W = nc * S, H = nr * S;
    const big = document.createElement("canvas");
    big.width = W; big.height = H;
    const bctx = big.getContext("2d", { willReadFrequently: true });
    bctx.fillStyle = "#000"; bctx.fillRect(0, 0, W, H);
    bctx.imageSmoothingEnabled = true; bctx.imageSmoothingQuality = "high";
    if ("filter" in bctx) bctx.filter = `blur(${(S * BLUR).toFixed(1)}px)`;
    bctx.drawImage(small, 0, 0, W, H);
    const src = bctx.getImageData(0, 0, W, H).data;
    // colour each pixel, and space the rows the way the map does (Web Mercator)
    const west = w0 - deg / 2 - PAD * deg, east = e0 + deg / 2 + PAD * deg;
    const south = Math.max(-85, s0 - deg / 2 - PAD * deg), north = Math.min(85, n0 + deg / 2 + PAD * deg);
    const mN = merc(north), mS = merc(south);
    const Hm = Math.max(1, Math.round((W * (mN - mS)) / (((east - west) * Math.PI) / 180)));
    const out = document.createElement("canvas");
    out.width = W; out.height = Hm;
    const octx = out.getContext("2d");
    const dst = octx.createImageData(W, Hm);
    for (let y = 0; y < Hm; y++) {
      const lat = unmerc(mN - ((y + 0.5) / Hm) * (mN - mS));
      const sy = Math.max(0, Math.min(H - 1, Math.floor(((north - lat) / (north - south)) * H)));
      for (let x = 0; x < W; x++) {
        const o = 4 * (sy * W + x), have = src[o + 1] / 255;
        if (have < 0.04) continue;
        // fringe: the colour also falls off toward the edge of a blob (counts); otherwise it holds
        const t = Math.min(1, src[o] / 255 / (fringe ? Math.max(have, 0.5) : have));
        const c = colours[Math.round(t * 255)], d = 4 * (y * W + x);
        dst.data[d] = c[0]; dst.data[d + 1] = c[1]; dst.data[d + 2] = c[2];
        dst.data[d + 3] = Math.round(255 * MAX_ALPHA * smooth(0.08, 0.34, have));
      }
    }
    octx.putImageData(dst, 0, 0);
    const at = (ll) => {
      const lon = ((ll.lng + 540) % 360) - 180;
      return index.get(`${Math.round((lon - w0) / deg)},${Math.round((ll.lat - s0) / deg)}`);
    };
    return { canvas: out, bounds: [[south, west], [north, east]], at };
  }

  function hover(e) {
    const c = grid && grid.at(e.latlng);
    if (!c) { if (tip) map.closeTooltip(tip); return; }
    tip = tip || L.tooltip({ direction: "top", offset: [0, -8], className: "fire-tip" });
    tip.setLatLng(e.latlng).setContent(grid.text(c));
    map.openTooltip(tip);
  }

  function draw(data, view, units, caption) {
    clearOverlay();
    const box = legend.getContainer();
    if (!data || view === "off" || !data.cells.length) {
      box.style.display = data && view !== "off" && !data.cells.length ? "" : "none";
      box.textContent = "No hotspots in these dates";
      return;
    }
    const deg = Math.max(data.cell_deg, binSize(map.getZoom()));
    lastDeg = deg;
    const cells = binned(data, deg);
    const vals = cells.map((c) => c.value).filter((v) => v > 0).sort(d3.ascending);
    const max = vals.length ? vals[vals.length - 1] : 1;
    const lo = vals.length ? d3.quantileSorted(vals, 0.05) : 0;
    // radar-style ramp on the map (yellow -> deep red); the calendar keeps its own scale
    const fire = (t) => d3.interpolateYlOrRd(0.28 + 0.72 * t);
    const scale = (v) => fire(FMT.countPos(v, max, lo));
    const anomalyPos = (c) => {            // same scale as FMT.anomalyColor: 0 = 10x less, 1 = 10x more
      if (!c.median || c.median <= 0) return c.value > 0 ? 0.92 : null;
      return 0.5 + Math.max(-1, Math.min(1, Math.log10(Math.max(c.value, 0.01) / c.median))) / 2;
    };
    const layer = view === "anomaly"
      ? radar(cells, deg, anomalyPos, ramp(d3.interpolatePuOr), false)
      : radar(cells, deg, (c) => (c.value > 0 ? FMT.countPos(c.value, max, lo) : null), ramp(fire), true);
    if (layer) {
      // a canvas element positioned and zoomed by Leaflet like an image
      overlay = L.svgOverlay(layer.canvas, layer.bounds, { interactive: false, className: "fire-radar" }).addTo(map);
      grid = { at: layer.at, deg, units, text: (c) => `<b>${FMT.int(c.value)}</b> ${units}<br>${ES ? "normal para estas fechas" : "normal for these dates"}: ${FMT.int(c.median)}` };
      if (layer.canvas.animate && !REDUCED)
        layer.canvas.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_MS, easing: "ease-out" });
    }
    const stops = d3.range(0, 1.0001, 0.1);
    const grad = view === "anomaly"
      ? stops.map((t) => d3.interpolatePuOr(t)).join(",")
      : stops.map((t) => scale(FMT.countAt(t, max, lo))).join(",");
    box.style.display = "";
    box.innerHTML = `<div>${caption}</div><div class="bar" style="background:linear-gradient(90deg,${grad})"></div>` +
      (view === "anomaly"
        ? (ES ? `<div class="ends"><span>10× menos</span><span>normal</span><span>10× más</span></div>`
            : `<div class="ends"><span>10× less</span><span>normal</span><span>10× more</span></div>`)
        : `<div class="ends"><span>${FMT.int(lo)}</span><span>${FMT.int(max)} ${units}</span></div>`) +
      `<div class="ends"><span>${ES ? "suavizado a partir de cuadros de" : "smoothed from"} ${deg === data.cell_deg ? "0.1°" : deg + "°"}${ES ? "" : " squares"}${deg > data.cell_deg ? (ES ? " (acerque para 0,1°)" : " (zoom in for 0.1°)") : ""}</span></div>` +
      (data.truncated ? (ES ? "<div>se muestran los 20.000 cuadros con más fuego</div>" : "<div>busiest 20,000 squares shown</div>") : "");
  }

  let mark = null;
  function highlight(bbox) {                  // outline one fire cluster and zoom to it
    if (mark) mark.remove();
    const [w, s_, e, n] = bbox;
    mark = L.rectangle([[s_, w], [n, e]], { color: "#c2410c", weight: 2.5, dashArray: "6 4", fill: false, interactive: false }).addTo(map);
    map.fitBounds(mark.getBounds(), { ...fitPad(), maxZoom: 9, animate: false });
  }
  function clearHighlight() { if (mark) { mark.remove(); mark = null; } }

  const invalidate = () => map && map.invalidateSize();
  // where the map is looking, for the opening globe to fly to: centre, zoom and the map's box on screen
  const view = () => map && { center: map.getCenter(), zoom: map.getZoom(), rect: map.getContainer().getBoundingClientRect() };
  return { init, show, invalidate, showCells, highlight, clearHighlight, view };
})();
