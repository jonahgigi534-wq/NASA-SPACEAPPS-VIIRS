// map.js: Leaflet map with our data regions outlined and draw tools (rectangle, polygon, circle).
// Whatever the user draws becomes an API "area" (docs/CONTRACTS.md section 4).
const MAP = (() => {
  let map, drawn, onArea;

  function init(regions, onAreaChosen) {
    onArea = onAreaChosen;
    map = L.map("map", { worldCopyJump: true, zoomControl: true }).setView([5, -40], 2);
    // OpenStreetMap's standard tiles: no API key, attribution required.
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
    return bounds;
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

  // draw an area that came from a preset or typed coordinates
  function show(area) {
    drawn.clearLayers();
    const style = { color: "#1d5fa8", weight: 2, fillOpacity: 0.04 };
    let layer;
    if (area.type === "bbox") { const [w, s, e, n] = area.bbox; layer = L.rectangle([[s, w], [n, e]], style); }
    else if (area.type === "point") layer = L.circle([area.lat, area.lon], { ...style, radius: area.radius_km * 1000 });
    else layer = L.polygon(area.coordinates[0].map(([x, y]) => [y, x]), style);
    drawn.addLayer(layer);
    map.fitBounds(layer.getBounds(), { padding: [20, 20], maxZoom: 8, animate: false });
  }

  // ---- fire on the map: one colored square per 0.1 degree cell (canvas, so thousands are fast)
  let cellLayer = null, renderer = null, legend = null, last = null;
  // Zoomed out, 0.1 degree squares are a pixel or two wide: merge them into bigger squares.
  function binSize(z) { return z <= 4 ? 0.5 : z <= 5 ? 0.25 : 0.1; }
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
    if (!cellLayer) {
      map.on("zoomend", () => last && draw(last.data, last.view, last.units, last.caption));
      renderer = L.canvas({ padding: 0.3 });
      cellLayer = L.layerGroup().addTo(map);
      legend = L.control({ position: "bottomleft" });
      legend.onAdd = () => { const d = L.DomUtil.create("div", "map-legend"); d.setAttribute("aria-hidden", "true"); return d; };
      legend.addTo(map);
    }
    draw(data, view, units, caption);
  }
  function draw(data, view, units, caption) {
    cellLayer.clearLayers();
    const box = legend.getContainer();
    if (!data || view === "off" || !data.cells.length) {
      box.style.display = data && view !== "off" && !data.cells.length ? "" : "none";
      box.textContent = "No hotspots in these dates";
      return;
    }
    const deg = Math.max(data.cell_deg, binSize(map.getZoom()));
    const cells = binned(data, deg);
    const vals = cells.map((c) => c.value).filter((v) => v > 0).sort(d3.ascending);
    const max = vals.length ? vals[vals.length - 1] : 1;
    const lo = vals.length ? d3.quantileSorted(vals, 0.05) : 0;
    const scale = FMT.countScale(max, lo);
    const half = deg / 2;
    cells.forEach((c) => {
      if (view === "counts" && c.value <= 0) return;
      const color = view === "anomaly" ? FMT.anomalyColor(c.value, c.median) : scale(c.value);
      L.rectangle([[c.lat - half, c.lon - half], [c.lat + half, c.lon + half]],
        { renderer, stroke: false, fillColor: color, fillOpacity: 0.8 })
        .bindTooltip(`<b>${FMT.int(c.value)}</b> ${units}<br>normal for these dates: ${FMT.int(c.median)}`, { sticky: true })
        .addTo(cellLayer);
    });
    const stops = d3.range(0, 1.0001, 0.1);
    const grad = view === "anomaly"
      ? stops.map((t) => d3.interpolatePuOr(t)).join(",")
      : stops.map((t) => scale(FMT.countAt(t, max, lo))).join(",");
    box.style.display = "";
    box.innerHTML = `<div>${caption}</div><div class="bar" style="background:linear-gradient(90deg,${grad})"></div>` +
      (view === "anomaly"
        ? `<div class="ends"><span>10× less</span><span>normal</span><span>10× more</span></div>`
        : `<div class="ends"><span>${FMT.int(lo)}</span><span>${FMT.int(max)} ${units}</span></div>`) +
      `<div class="ends"><span>${deg === data.cell_deg ? "0.1°" : deg + "°"} squares${deg > data.cell_deg ? " (zoom in for 0.1°)" : ""}</span></div>` +
      (data.truncated ? "<div>busiest 20,000 squares shown</div>" : "");
  }

  const invalidate = () => map && map.invalidateSize();
  return { init, show, invalidate, showCells };
})();
