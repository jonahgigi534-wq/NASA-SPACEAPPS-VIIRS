// globe.js: the 3D globe shown when the site opens. The reader picks one of our data regions and
// the globe flies down to it, then fades into the dashboard map, which is already looking at the
// same place. It opens whenever the opening story plays (js/intro.js), with ?globe=1, or from the
// "Pick a region on the globe" button on the dashboard; ?globe=0 turns it off.
// The globe is MapLibre GL JS (loaded only when needed) drawing OpenStreetMap tiles. If it can't
// load or the browser has no WebGL, the region buttons still work without the globe.
const GLOBE = (() => {
  const root = document.getElementById("globe");
  if (!root) return { open() {} };
  const params = new URLSearchParams(location.search);
  const T = { title: "Where do you want to look?", sub: "Pick a region. Spin the globe if you like.",
              skip: "Just open the dashboard", back: "Go back to where I was" };
  const LIB = "https://cdn.jsdelivr.net/npm/maplibre-gl@5.6.0/dist/maplibre-gl";
  const SPIN_DEG_PER_S = 5, GLOBE_SHARE = 0.95, FLY_MS = 3400;   // FLY_MS matches the slide in globe.css
  const FADE_MS = 800, APP_WAIT_MS = 20000;
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const ui = root.querySelector(".globe-ui"), choices = document.getElementById("globe-choices");
  const skipBtn = document.getElementById("globe-skip");
  let map = null, regions = null, spinning = false, leaving = false, isOpen = false, libPromise = null;

  const centre = (r) => [(r.bbox[0] + r.bbox[2]) / 2, (r.bbox[1] + r.bbox[3]) / 2];
  const wait = (ms) => new Promise((res) => setTimeout(res, ms));

  function loadLib() {
    if (libPromise) return libPromise;
    libPromise = new Promise((resolve, reject) => {
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = `${LIB}.css`;
      document.head.appendChild(css);
      const js = document.createElement("script");
      js.src = `${LIB}.js`; js.onload = resolve; js.onerror = () => reject(new Error("globe library did not load"));
      document.head.appendChild(js);
    });
    return libPromise;
  }

  function spin() {
    let lastT = null;
    const step = (t) => {
      if (!spinning || !map) return;
      if (lastT != null) {
        const c = map.getCenter();
        map.jumpTo({ center: [c.lng - (SPIN_DEG_PER_S * (t - lastT)) / 1000, c.lat] });
      }
      lastT = t;
      requestAnimationFrame(step);
    };
    spinning = !REDUCED;
    if (spinning) requestAnimationFrame(step);
  }
  const stopSpin = () => { spinning = false; };

  function buildMap() {
    // a big globe: about as wide as the screen is tall (less on a narrow phone). On a globe,
    // MapLibre draws the world 512 * 2^zoom px around, so the globe is that / pi across.
    const across = Math.min(window.innerHeight * GLOBE_SHARE, window.innerWidth * 1.5);
    map = new maplibregl.Map({
      container: "globe-map",
      style: {
        version: 8,
        projection: { type: "globe" },
        sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 12,
                          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' } },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
        sky: { "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 4, 1, 6, 0] },
      },
      center: [-55, -5], zoom: Math.log2((across * Math.PI) / 512),
      dragRotate: false, pitchWithRotate: false, touchPitch: false, attributionControl: { compact: true },
    });
    ["mousedown", "touchstart", "wheel"].forEach((ev) => map.getCanvas().addEventListener(ev, stopSpin, { passive: true }));
    (regions || []).forEach((r) => {
      const pin = document.createElement("button");
      pin.type = "button"; pin.className = "globe-pin"; pin.title = r.name; pin.setAttribute("aria-label", r.name);
      pin.addEventListener("click", () => choose(r));
      new maplibregl.Marker({ element: pin }).setLngLat(centre(r)).addTo(map);
    });
    // start turning only once the opening story has lifted, so the first thing seen is the Americas
    const startSpin = () => (document.getElementById("intro") ? setTimeout(startSpin, 250) : spin());
    map.once("load", startSpin);
  }

  function renderChoices() {
    choices.innerHTML = "";
    (regions || []).forEach((r) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "globe-choice"; b.textContent = r.name;
      const look = () => {                                    // turn the globe to face the region
        if (!map || leaving) return;
        stopSpin();
        map.easeTo({ center: centre(r), duration: 1100 });
      };
      b.addEventListener("mouseenter", look);
      b.addEventListener("focus", look);
      b.addEventListener("click", () => choose(r));
      choices.appendChild(b);
    });
  }

  // the dashboard (js/app.js) says it is ready by setting window.FireBridgeApp
  async function appReady() {
    const t0 = Date.now();
    while (!window.FireBridgeApp && Date.now() - t0 < APP_WAIT_MS) await wait(100);
    return window.FireBridgeApp || null;
  }

  async function choose(r) {
    if (leaving) return;
    leaving = true;
    stopSpin();
    ui.classList.add("out");
    const app = await appReady();
    window.scrollTo(0, 0);
    const ok = app && app.chooseRegion(r.id);
    const v = ok && typeof MAP !== "undefined" && MAP.view();
    if (!map || !v || REDUCED) { close(); return; }
    // fly to exactly what the dashboard map shows: same centre, same scale (MapLibre zoom is one
    // less than Leaflet's for the same view), and the same box on screen
    root.classList.add("flying");
    let closed = false;
    const done = () => { if (!closed) { closed = true; close(); } };
    setTimeout(done, FLY_MS + 1500);                           // in case the move never reports its end
    map.stop();                                                // end any turn in progress before listening for the end
    map.flyTo({
      center: [v.center.lng, v.center.lat], zoom: v.zoom - 1, duration: FLY_MS, curve: 1.25, essential: true,
      padding: { top: v.rect.top, left: v.rect.left, right: Math.max(0, window.innerWidth - v.rect.right),
                 bottom: Math.max(0, window.innerHeight - v.rect.bottom) },
    });
    map.once("moveend", done);
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    stopSpin();
    root.classList.add("out");
    document.documentElement.classList.remove("globe-on");
    setTimeout(() => {
      root.hidden = true;
      root.classList.remove("out", "flying");
      if (map) { map.remove(); map = null; }
      if (typeof MAP !== "undefined") MAP.invalidate();
    }, FADE_MS + 50);
  }

  async function open() {
    if (isOpen) return;
    isOpen = true; leaving = false;
    document.getElementById("globe-title").textContent = T.title;
    root.querySelector(".globe-sub").textContent = T.sub;
    skipBtn.textContent = location.hash.length > 1 ? T.back : T.skip;
    ui.classList.remove("out");
    root.classList.remove("out", "flying");
    root.hidden = false;
    document.documentElement.classList.add("globe-on");
    try {
      if (!regions) regions = (await fetch("/api/regions").then((res) => { if (!res.ok) throw new Error(res.status); return res.json(); })).regions;
    } catch { close(); return; }                               // no data yet (server waking): show the dashboard, which explains
    if (!isOpen) return;
    renderChoices();
    try { await loadLib(); if (isOpen && !map) buildMap(); } catch { /* no globe: the buttons still work */ }
  }

  skipBtn.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen && !document.getElementById("intro")) close(); });

  const auto = window.FireBridgeIntro === true && params.get("globe") !== "0";
  if (params.get("globe") === "1" || auto) open();
  return { open, close };
})();
