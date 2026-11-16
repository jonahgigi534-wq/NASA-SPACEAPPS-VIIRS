// space.js: the scene around the opening globe (js/globe.js calls SPACE.onOpen / onClose).
// Earth floats in a starfield. Scrolling down the screen moves the globe away and lifts glowing
// embers past the camera one at a time, each labelled like a HUD readout; clicking one opens a
// short plain-language panel ("how it works", the test results, the live check, the judges' tour).
// At the end the embers circle the globe and the reader is sent to the dashboard.
// The embers are drawn on a 2D canvas as small rotating rocks with hot faces. Each one also has a
// real <button> over it, so they work with the keyboard and screen readers. With reduced motion
// nothing moves: the embers become a list of cards under the globe.
// Every number in the panels comes from /content/metrics.json or /api/unusual.
(() => {
  const root = document.getElementById("globe");
  if (!root) return;
  const q = (sel) => root.querySelector(sel);
  const stage = q(".space-stage"), track = q(".space-track"), ui = q(".globe-ui"), finale = q(".space-finale");
  const starsCv = q(".space-stars"), emberCv = q(".space-embers"), list = document.getElementById("ember-list");
  const panel = document.getElementById("ember-panel"), body = document.getElementById("ember-body");
  const closeBtn = document.getElementById("ember-close");
  const params = new URLSearchParams(location.search);
  const CALM = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // the scroll story, in screen heights
  const HERO = 0.35, LEAVE = 0.8, PER = 1, FIN_IN = 0.7, FINALE = 1.1;
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (t) => t * t * (3 - 2 * t);
  let vw = innerWidth, vh = innerHeight;

  // ---------- the content (numbers filled in from the API) ----------
  const data = { metrics: null, unusual: null, loading: null };
  function load() {
    if (data.loading) return data.loading;
    const get = (u) => fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    data.loading = Promise.all([get("/content/metrics.json"), get("/api/unusual")])
      .then(([m, u]) => { data.metrics = m; data.unusual = u; });
    return data.loading;
  }
  const pct = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}%`;
  const int = (x) => Math.round(Math.abs(x)).toLocaleString("en-US");
  const span = (y) => (y ? `${y[0]}–${y[1]}` : "");
  const m = (d, path) => path.split(".").reduce((o, k) => (o == null ? null : o[k]), d.metrics);

  const EMBERS = [
    { slug: "problem", title: "The problem", tag: "2012 · A sharper camera",
      build(d) {
        const raw = m(d, "overall.holdout.raw_viirs.bias_pct");
        return {
          paras: [
            "Satellites have watched Earth's fires since 2000 with a camera called MODIS. It reports hotspots: small patches of ground hot enough to be burning as it passes over.",
            raw == null ? "In 2012 a sharper camera, VIIRS, joined. Over the same places it sees far more small fires than MODIS."
              : `In 2012 a sharper camera, VIIRS, joined. Over the same places and months it counted ${pct(raw)} more hotspots than MODIS on our test years: about ${(1 + raw / 100).toFixed(1)} times as many.`,
            "Join the two records and fire seems to explode in 2012. It didn't. The camera changed.",
          ],
          facts: raw == null ? [] : [["Raw VIIRS vs MODIS", pct(raw)], ["Same fires, counted", `${(1 + raw / 100).toFixed(1)}×`]],
          links: [{ label: "How it works →", href: "/methods" }],
        };
      } },
    { slug: "fix", title: "Our fix", tag: "One scale · 2001 → today",
      build(d) {
        const base = m(d, "baseline_years"), harm = m(d, "overall.holdout.harmonized.bias_pct");
        return {
          paras: [
            `${base ? `From ${span(base)}` : "For several years"} both cameras flew at the same time, so we could see how VIIRS counts line up with MODIS counts for the same places and months, region by region.`,
            "We used that overlap to translate every VIIRS count onto the MODIS scale (quantile mapping beat the other methods we tried). The result is one record from 2001 to today, with no fake jump in 2012.",
            "In the dashboard this is the Harmonized record. Switch to Raw VIIRS and the jump comes back.",
          ],
          facts: [base && ["Learned from", span(base)], harm != null && ["Bias after the fix", pct(harm)]].filter(Boolean),
          links: [{ label: "How it works →", href: "/methods" }],
        };
      } },
    { slug: "proof", title: "Proof it works", tag: "Tested on years it never saw",
      build(d) {
        const base = m(d, "baseline_years"), test = m(d, "test_years");
        const h = m(d, "overall.holdout"), n = m(d, "overall.transfer_noaa20");
        if (!h || !n || !test) return { paras: ["The test results are loading. They are also on the More checks page."], facts: [], links: [{ label: "More checks →", href: "/checks" }] };
        return {
          paras: [
            `We learned on ${span(base)} and tested on ${test[0]} → ${test[1]}, years the method never saw.`,
            `On those years the harmonized record is off from MODIS by ${pct(h.harmonized.bias_pct)} overall. Raw VIIRS is off by ${pct(h.raw_viirs.bias_pct)}.`,
            `Typical monthly error is ${int(h.harmonized.rmse)} hotspots, against ${int(h.global_ratio.rmse)} for one simple global ratio. On NOAA-20, a second VIIRS satellite never used in fitting: ${int(n.harmonized.rmse)} against ${int(n.global_ratio.rmse)}.`,
          ],
          facts: [["Bias, test years", pct(h.harmonized.bias_pct)], ["Monthly error (RMSE)", int(h.harmonized.rmse)], ["NOAA-20 error", int(n.harmonized.rmse)]],
          links: [{ label: "More checks →", href: "/checks" }, { label: "How it works →", href: "/methods" }],
        };
      } },
    { slug: "read", title: "How to read the dashboard", tag: "Three steps",
      build() {
        return {
          paras: [
            "1. Pick a place: one of the glowing regions, a big fire event, or a box you draw on the map.",
            "2. Read the big number: how many fire hotspots satellites spotted there in your dates.",
            "3. Check “vs normal”: 1× is a normal year for those dates. Above 1× means more fire than usual, below means less.",
            "Stuck on a number? Press the “?” next to it.",
          ],
          facts: [],
          links: [{ label: "Open the dashboard", action: "open" }],
        };
      } },
    { slug: "live", title: "Unusual right now", tag: "Live satellite feed",
      build(d) {
        const u = d.unusual;
        if (!u) return { paras: ["The live check is not available right now. The dashboard's “Unusual right now” list shows it when it is."], facts: [], links: [{ label: "Open the dashboard", action: "open" }] };
        const rule = `We flag a one-degree square when it has at least ${u.min_hotspots} hotspots and ${u.min_pct / 100}× its normal for the same days of the month (normal = median of ${span(u.baseline)}).`;
        const tiles = u.tiles || [];
        if (!tiles.length) {
          return {
            paras: [`As of ${u.as_of}, nothing is unusually busy.`, rule,
              ...(u.days_so_far < 7 ? [`It is early in the month (${u.days_so_far} day${u.days_so_far === 1 ? "" : "s"} of data so far), so this can change quickly.`] : []),
              "This check runs on the live satellite feed, so it updates by itself."],
            facts: [["As of", u.as_of], ["Flagged squares", "0"]],
            links: [{ label: "Open the dashboard", action: "open" }],
          };
        }
        const score = (tl) => (tl.median > 0 ? tl.value / tl.median : tl.value);
        const top = tiles.reduce((a, b) => (score(b) > score(a) ? b : a));
        return {
          paras: [`As of ${u.as_of}, ${u.tiles_total} one-degree square${u.tiles_total === 1 ? " is" : "s are"} far busier than normal for this point in the month.`,
            `The most unusual: ${top.region_name}, near ${top.lat.toFixed(1)}°, ${top.lon.toFixed(1)}°, with ${int(top.value)} hotspots against a normal ${int(top.median)}.`, rule],
          facts: [["As of", u.as_of], ["Flagged squares", String(u.tiles_total)], ["Hotspots there", int(top.value)]],
          links: [{ label: `Open ${top.region_name}`, action: "region", id: top.region }],
        };
      } },
    { slug: "checks", title: "More checks", tag: "Every test we ran",
      build() {
        return {
          paras: ["More ways we tested the harmonized record, region by region, with the tables and figures behind them.",
            "Every number on the site is computed from our results files, not typed in by hand."],
          facts: [], links: [{ label: "More checks →", href: "/checks" }],
        };
      } },
    { slug: "judges", title: "For judges", tag: "Two-minute tour",
      build() {
        return {
          paras: ["Each line of the challenge brief, next to the one click in the live app that shows it.",
            "Every link opens a prepared view, and the address bar keeps it, so any screen can be shared."],
          facts: [], links: [{ label: "For judges →", href: "/judges" }],
        };
      } },
  ];
  const N = EMBERS.length;
  const code = (i) => `EMBER_${String(i + 1).padStart(2, "0")}`;
  const centreOf = (i) => HERO + LEAVE * 0.7 + (i + 0.5) * PER;     // scroll position (screens) where ember i is centred
  const finaleAt = HERO + LEAVE * 0.7 + N * PER + 0.05;

  // ---------- the buttons (one per ember) ----------
  const hits = EMBERS.map((e, i) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button"; b.className = "ember-hit";
    const label = document.createElement("span");
    label.className = "ember-card-text";
    label.textContent = e.title;
    const small = document.createElement("small");
    small.textContent = ` ${e.tag}`;
    label.appendChild(small);
    b.appendChild(label);
    b.addEventListener("click", () => openPanel(i));
    b.addEventListener("focus", () => { if (!CALM && !b.classList.contains("on")) root.scrollTo({ top: centreOf(i) * vh, behavior: "smooth" }); });
    li.appendChild(b);
    list.appendChild(li);
    return b;
  });

  // ---------- the panel ----------
  let openIdx = -1, lastFocus = null;
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function linkRow(links) {
    const row = el("div", "ember-links");
    links.forEach((l, k) => {
      let a;
      if (l.href) { a = el("a", "space-btn", l.label); a.href = l.href; }
      else {
        a = el("button", "space-btn", l.label); a.type = "button";
        a.addEventListener("click", () => {
          closePanel(true);
          if (typeof GLOBE === "undefined") return;
          if (l.action === "region") GLOBE.chooseId(l.id); else GLOBE.close();
        });
      }
      if (k === 0) a.classList.add("primary");
      row.appendChild(a);
    });
    return row;
  }
  function render(i) {
    const e = EMBERS[i], c = e.build(data);
    const h = el("h2", null, e.title); h.id = "ember-title";
    const out = [el("span", "hud-k", `////// ${code(i)}`), h, el("p", "ember-tag", e.tag.toUpperCase()), el("span", "hud-k", "/// Summary")];
    c.paras.forEach((t) => out.push(el("p", null, t)));
    if (c.facts.length) {
      out.push(el("span", "hud-k", "/// In numbers"));
      const g = el("div", "ember-facts");
      c.facts.forEach(([k, v]) => { const f = el("div", "ember-fact"); f.append(el("span", null, k), el("b", null, v)); g.appendChild(f); });
      out.push(g);
    }
    if (c.links.length) out.push(el("span", "hud-k", "/// Go deeper"), linkRow(c.links));
    body.replaceChildren(...out);
  }
  function setHow(slug) {
    try {
      const url = new URL(location.href);
      if (slug) url.searchParams.set("how", slug); else url.searchParams.delete("how");
      history.replaceState(history.state, "", url);
    } catch { /* the address bar is a convenience only */ }
  }
  function openPanel(i) {
    openIdx = i;
    lastFocus = document.activeElement;
    render(i);
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add("on"));
    panel.scrollTop = 0;
    closeBtn.focus();
    setHow(EMBERS[i].slug);
    if (!data.metrics || !data.unusual) load().then(() => { if (openIdx === i) render(i); });
  }
  function closePanel(quiet) {
    if (panel.hidden) return;
    openIdx = -1;
    panel.classList.remove("on");
    setTimeout(() => { if (openIdx < 0) panel.hidden = true; }, CALM ? 0 : 350);
    setHow(null);
    if (!quiet && lastFocus && lastFocus.isConnected) lastFocus.focus();
  }
  closeBtn.addEventListener("click", () => closePanel());
  panel.addEventListener("click", (e) => { if (e.target === panel) closePanel(); });
  // Escape closes an open panel first (the globe itself also closes on Escape, see globe.js)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) { e.stopImmediatePropagation(); e.preventDefault(); closePanel(); }
  }, true);
  document.getElementById("space-top").addEventListener("click", () => root.scrollTo({ top: 0, behavior: CALM ? "auto" : "smooth" }));
  document.getElementById("space-open").addEventListener("click", () => { if (typeof GLOBE !== "undefined") GLOBE.close(); });

  // ---------- the rocks: a jittered, once-subdivided icosahedron per ember ----------
  const PHI = (1 + Math.sqrt(5)) / 2;
  const ICO_V = [[-1, PHI, 0], [1, PHI, 0], [-1, -PHI, 0], [1, -PHI, 0], [0, -1, PHI], [0, 1, PHI], [0, -1, -PHI], [0, 1, -PHI], [PHI, 0, -1], [PHI, 0, 1], [-PHI, 0, -1], [-PHI, 0, 1]];
  const ICO_F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  const norm = (p) => { const l = Math.hypot(p[0], p[1], p[2]) || 1; return [p[0] / l, p[1] / l, p[2] / l]; };
  const seeded = (seed) => { let s = (seed % 2147483646) + 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; };
  function subdivide(v, f) {
    const verts = v.map(norm), mids = new Map();
    const mid = (a, b) => {
      const k = a < b ? `${a}_${b}` : `${b}_${a}`;
      if (!mids.has(k)) { verts.push(norm([(verts[a][0] + verts[b][0]) / 2, (verts[a][1] + verts[b][1]) / 2, (verts[a][2] + verts[b][2]) / 2])); mids.set(k, verts.length - 1); }
      return mids.get(k);
    };
    const faces = [];
    f.forEach(([a, b, c]) => { const ab = mid(a, b), bc = mid(b, c), ca = mid(c, a); faces.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]); });
    return { verts, faces };
  }
  const SPHERE = subdivide(ICO_V, ICO_F);
  function makeRock(seed) {
    const r = seeded(seed * 7919 + 13);
    const sx = 0.8 + r() * 0.25, sy = 1.1 + r() * 0.35, sz = 0.8 + r() * 0.25;
    const verts = SPHERE.verts.map((p) => { const k = 0.76 + r() * 0.34; return [p[0] * k * sx, p[1] * k * sy, p[2] * k * sz]; });
    const faces = SPHERE.faces.map((idx) => ({ idx, heat: Math.pow(r(), 2.4), ph: r() * 6.283 }));
    return { verts, faces };
  }
  const ROCKS = EMBERS.map((_, i) => makeRock(i + 3));
  const LIGHT = norm([-0.35, 0.55, 0.76]);

  function project(rock, x, y, R, rx, ry) {
    const cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
    return rock.verts.map(([a, b, c]) => {
      const X = a * cy + c * sy, Z0 = -a * sy + c * cy;
      const Y = b * cx - Z0 * sx, Z = b * sx + Z0 * cx;
      const k = 3.2 / (3.2 - Z);
      return [x + X * R * k, y - Y * R * k, X, Y, Z];
    });
  }
  function visibleFaces(rock, P) {
    const vis = [];
    for (const f of rock.faces) {
      const [A, B, C] = f.idx.map((k) => P[k]);
      const ux = B[2] - A[2], uy = B[3] - A[3], uz = B[4] - A[4], vx = C[2] - A[2], vy = C[3] - A[3], vz = C[4] - A[4];
      let n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
      const mx = A[2] + B[2] + C[2], my = A[3] + B[3] + C[3], mz = A[4] + B[4] + C[4];
      if (n[0] * mx + n[1] * my + n[2] * mz < 0) n = [-n[0], -n[1], -n[2]];   // point outward
      n = norm(n);
      if (n[2] > 0) vis.push({ f, A, B, C, n, z: mz });
    }
    return vis.sort((a, b) => a.z - b.z);
  }
  const tri = (ctx, v) => { ctx.beginPath(); ctx.moveTo(v.A[0], v.A[1]); ctx.lineTo(v.B[0], v.B[1]); ctx.lineTo(v.C[0], v.C[1]); ctx.closePath(); };
  function drawRock(ctx, rock, x, y, R, t, rx, ry, glow) {
    const halo = ctx.createRadialGradient(x, y, R * 0.2, x, y, R * 2.7);
    halo.addColorStop(0, `rgba(255,120,30,${(0.34 * glow).toFixed(3)})`);
    halo.addColorStop(0.45, `rgba(255,80,10,${(0.12 * glow).toFixed(3)})`);
    halo.addColorStop(1, "rgba(255,60,0,0)");
    ctx.fillStyle = halo;
    ctx.fillRect(x - R * 2.7, y - R * 2.7, R * 5.4, R * 5.4);
    const vis = visibleFaces(rock, project(rock, x, y, R, rx, ry));
    for (const v of vis) {
      const diff = Math.max(0, v.n[0] * LIGHT[0] + v.n[1] * LIGHT[1] + v.n[2] * LIGHT[2]);
      const heat = clamp((v.f.heat * 0.85 + clamp(-v.n[1]) * 0.45) * (0.65 + 0.35 * Math.sin(t * 2.2 + v.f.ph)) * glow);
      const r = Math.min(255, 26 + 60 * diff + 240 * heat), g = Math.min(255, 14 + 30 * diff + 120 * heat * heat), b = Math.min(255, 10 + 22 * diff + 30 * heat * heat * heat);
      const col = `rgb(${r | 0},${g | 0},${b | 0})`;
      tri(ctx, v);
      ctx.fillStyle = col; ctx.strokeStyle = col; ctx.lineWidth = 0.8;
      ctx.fill(); ctx.stroke();
    }
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = `rgba(255,120,30,${(0.2 * glow).toFixed(3)})`; ctx.lineWidth = 1;
    for (const v of vis) { if (v.f.heat >= 0.35) { tri(ctx, v); ctx.stroke(); } }
    ctx.globalCompositeOperation = "source-over";
  }

  // HUD text that "decodes" from random characters as it appears
  const NOISE = "#%&*+/<>=_01ABCDEFXZ";
  const decode = (text, r) => [...text].map((ch, k) => (ch === " " || k / text.length < r ? ch : NOISE[(Math.random() * NOISE.length) | 0])).join("");

  function drawCallouts(ctx, i, x, y, R, a) {
    const e = EMBERS[i], rev = clamp((a - 0.15) / 0.6), narrow = vw < 640;
    const lineH = narrow ? 14 : 16;
    ctx.save();
    ctx.globalAlpha = a;
    ctx.font = `500 ${narrow ? 11 : 12}px "IBM Plex Mono", ui-monospace, monospace`;
    ctx.fillStyle = "rgba(241,237,230,.92)"; ctx.strokeStyle = "rgba(241,237,230,.7)"; ctx.lineWidth = 1;
    const block = (lines, bx, by, toX, toY, alignRight) => {
      const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 6;
      const left = clamp(alignRight ? bx - w : bx, 12, vw - w - 12);
      lines.forEach((l, k) => ctx.fillText(decode(l, rev), left, by + k * lineH));
      const uy = by + (lines.length - 1) * lineH + 8, anchorX = alignRight ? left : left + w;
      ctx.beginPath(); ctx.moveTo(left, uy); ctx.lineTo(left + w, uy); ctx.moveTo(anchorX, uy); ctx.lineTo(toX, toY); ctx.stroke();
      ctx.fillRect(toX - 3, toY - 0.5, 6, 1); ctx.fillRect(toX - 0.5, toY - 3, 1, 6);
    };
    block([code(i), e.title.toUpperCase()], narrow ? x - R * 0.9 : x - R * 2.4, y - R * (narrow ? 1.9 : 1.25), x - R * 0.5, y - R * 0.55, false);
    block([e.tag.toUpperCase(), "CLICK TO EXPLORE"], narrow ? x + R * 0.9 : x + R * 2.4, y + R * (narrow ? 1.6 : 0.9), x + R * 0.5, y + R * 0.45, true);
    ctx.restore();
  }

  // ---------- stars and drifting sparks ----------
  let stars = [];
  const sparks = [];
  function makeStars() {
    const r = seeded(42), n = Math.min(900, Math.round((vw * vh) / 2600));
    stars = Array.from({ length: n }, () => ({ x: r() * vw, y: r() * vh, z: 0.2 + r() * 0.8, s: r() < 0.07 ? 2 : 1, tw: 0.5 + r() * 2, ph: r() * 6.283 }));
  }
  function drawStars(s, t) {
    const ctx = starsCv.getContext("2d");
    ctx.clearRect(0, 0, vw, vh);
    const neb = ctx.createRadialGradient(vw * 0.82, vh * 0.18, 0, vw * 0.82, vh * 0.18, vw * 0.5);
    neb.addColorStop(0, "rgba(120,60,140,.10)"); neb.addColorStop(1, "rgba(120,60,140,0)");
    ctx.fillStyle = neb; ctx.fillRect(0, 0, vw, vh);
    for (const st of stars) {
      const y = (((st.y - s * vh * 0.08 * st.z) % vh) + vh) % vh;
      const a = (0.25 + 0.6 * st.z) * (CALM ? 1 : 0.75 + 0.25 * Math.sin(t * st.tw + st.ph));
      ctx.fillStyle = `rgba(255,248,235,${a.toFixed(3)})`;
      ctx.fillRect(st.x, y, st.s, st.s);
    }
  }
  function drawSparks(ctx) {
    if (sparks.length < 46 && Math.random() < 0.5) {
      sparks.push({ x: Math.random() * vw, y: vh + 10, vx: (Math.random() - 0.5) * 0.4, vy: -(0.4 + Math.random() * 1.1), life: 0, max: 200 + Math.random() * 260, r: 0.6 + Math.random() * 1.6 });
    }
    ctx.globalCompositeOperation = "lighter";
    for (let k = sparks.length - 1; k >= 0; k--) {
      const p = sparks[k];
      p.life++; p.x += p.vx + Math.sin(p.life * 0.04) * 0.25; p.y += p.vy;
      if (p.life > p.max || p.y < -10) { sparks.splice(k, 1); continue; }
      const a = Math.sin((p.life / p.max) * Math.PI) * 0.8;
      ctx.fillStyle = `rgba(255,${(110 + 90 * a) | 0},30,${a.toFixed(3)})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  // ---------- one frame: everything follows the scroll position ----------
  const setVar = (k, v) => root.style.setProperty(k, v);
  function sceneVars(s) {
    const out = smooth(clamp((s - HERO) / LEAVE));
    const fin = smooth(clamp((s - finaleAt) / FIN_IN));
    setVar("--globe-y", `${lerp(lerp(0, -0.36 * vh, out), -0.2 * vh, fin).toFixed(1)}px`);   // finale: globe centred at 44% height
    setVar("--globe-s", lerp(lerp(1, 0.4, out), 0.56, fin).toFixed(3));
    setVar("--globe-o", lerp(lerp(1, 0.55, out), 1, fin).toFixed(3));
    setVar("--ui-o", (1 - clamp(out * 1.8)).toFixed(3));
    setVar("--ui-y", `${(-30 * out).toFixed(1)}px`);
    ui.classList.toggle("hidden", out > 0.4);
    setVar("--hint-o", (1 - clamp(s / 0.3)).toFixed(3));
    setVar("--kick-o", (clamp((out - 0.5) * 2) * (1 - fin)).toFixed(3));
    setVar("--fin-o", fin.toFixed(3));
    finale.classList.toggle("on", fin > 0.6);
    const max = root.scrollHeight - root.clientHeight;
    setVar("--prog", (max > 0 ? root.scrollTop / max : 0).toFixed(3));
    return fin;
  }
  function emberPositions(s, t, fin) {
    const base = Math.min(vw, vh) * (vw < 640 ? 0.16 : 0.12), ringR = Math.min(vw, vh) * 0.34;
    return EMBERS.map((_, i) => {
      const u = (s - centreOf(i)) / PER;
      let x = vw / 2 + Math.sin(i * 2.1) * vw * 0.05;
      let y = vh * 0.52 - Math.sign(u) * Math.pow(Math.min(Math.abs(u), 1.5), 1.3) * vh * 0.72;
      let R = base * (1 - 0.3 * clamp(Math.abs(u)));
      if (fin > 0) {
        const ang = (i / N) * Math.PI * 2 + t * 0.12 - Math.PI / 2;
        x = lerp(x, vw / 2 + Math.cos(ang) * ringR * 1.25, fin);
        y = lerp(y, vh * 0.44 + Math.sin(ang) * ringR * 0.74, fin);
        R = lerp(R, base * 0.42, fin);
      }
      const a = clamp(1 - Math.abs(u) / 0.28) * (1 - fin);
      return { x, y, R, a, u, on: s > HERO * 0.5 && y > -R * 3 && y < vh + R * 3 };
    });
  }
  function layout(s, t) {
    const fin = sceneVars(s);
    drawStars(s, t);
    const ctx = emberCv.getContext("2d");
    ctx.clearRect(0, 0, vw, vh);
    drawSparks(ctx);
    const pos = emberPositions(s, t, fin);
    let best = -1;
    pos.forEach((p, i) => {
      if (p.on) drawRock(ctx, ROCKS[i], p.x, p.y, p.R, t, 0.3 + 0.35 * Math.sin(t * 0.3 + i), t * 0.35 + i * 1.7 + s * 0.8, 0.55 + 0.45 * Math.max(p.a, fin * 0.6));
      if (p.a > 0.02 && (best < 0 || p.a > pos[best].a)) best = i;
      const hit = hits[i], clickable = p.on && (Math.abs(p.u) < 0.45 || fin > 0.8);
      hit.classList.toggle("on", clickable);
      if (clickable) {
        hit.style.width = hit.style.height = `${(p.R * 2.2).toFixed(0)}px`;
        hit.style.transform = `translate(${(p.x - p.R * 1.1).toFixed(1)}px, ${(p.y - p.R * 1.1).toFixed(1)}px)`;
      }
    });
    if (best >= 0) drawCallouts(ctx, best, pos[best].x, pos[best].y, pos[best].R, pos[best].a);
  }

  // ---------- run only while the screen is open ----------
  let running = false, raf = 0;
  const t0 = performance.now();
  function size() {
    vw = innerWidth; vh = stage.clientHeight || innerHeight;
    if (CALM) vh = innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    [starsCv, emberCv].forEach((cv) => {
      cv.width = Math.round(vw * dpr); cv.height = Math.round(vh * dpr);
      cv.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    });
    track.style.height = CALM ? "" : `${Math.round((1 + finaleAt + FIN_IN + FINALE) * vh)}px`;
    makeStars();
  }
  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    layout(root.scrollTop / vh, (now - t0) / 1000);
  }
  function start() {
    root.classList.toggle("calm", CALM);
    size();
    if (CALM) { drawStars(0, 0); return; }
    if (running) return;
    running = true;
    raf = requestAnimationFrame(frame);
  }
  function stop() { running = false; cancelAnimationFrame(raf); }
  addEventListener("resize", () => { if (!root.hidden) { size(); if (CALM) drawStars(0, 0); } });

  // a shared link like /?how=proof opens that ember straight away
  function deepLink() {
    const i = EMBERS.findIndex((e) => e.slug === params.get("how"));
    params.delete("how");
    if (i < 0) return;
    setTimeout(() => {
      if (!CALM) root.scrollTop = centreOf(i) * vh;
      openPanel(i);
    }, 400);
  }

  window.SPACE = Object.freeze({
    onOpen() { root.scrollTop = 0; start(); load(); deepLink(); },
    onClose() { stop(); closePanel(true); },
    toTop() { root.scrollTop = 0; },
  });
})();
