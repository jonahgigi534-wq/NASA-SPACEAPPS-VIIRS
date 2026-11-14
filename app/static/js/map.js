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
    const style = { color: "#1d5fa8", weight: 2, fillOpacity: 0.12 };
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
    const style = { color: "#1d5fa8", weight: 2, fillOpacity: 0.12 };
    let layer;
    if (area.type === "bbox") { const [w, s, e, n] = area.bbox; layer = L.rectangle([[s, w], [n, e]], style); }
    else if (area.type === "point") layer = L.circle([area.lat, area.lon], { ...style, radius: area.radius_km * 1000 });
    else layer = L.polygon(area.coordinates[0].map(([x, y]) => [y, x]), style);
    drawn.addLayer(layer);
    map.fitBounds(layer.getBounds(), { padding: [20, 20], maxZoom: 8, animate: false });
  }

  const invalidate = () => map && map.invalidateSize();
  return { init, show, invalidate };
})();
