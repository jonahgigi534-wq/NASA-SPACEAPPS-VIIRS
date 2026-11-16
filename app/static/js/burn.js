// burn.js: the fire transitions used by the opening story (js/intro.js).
//   FireBurn.line(el, ms, sparkHost)          burns one line of text away: noisy holes eat the
//                                             letters with a glowing ember edge, and sparks drift up.
//   FireBurn.page(host, ms, paper, sparkHost)  burns the page from the centre outward: a ragged hole
//                                             with a glowing rim spreads until the page is gone and
//                                             whatever is underneath (the globe) shows.
// Both return a promise that resolves when the burn is done. Pure decoration, no data.
(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const KEEP_SLOPE = 14;          // how sharp the burn edge is in the text filter
  const EMBER_AHEAD = 2.2;        // how far the ember ring runs ahead of the burnt edge
  const PAGE_SCALE = 4;           // the page fire is drawn at 1/4 resolution and smoothed up
  const RIM = 0.075;              // width of the glowing rim, as a share of the burn distance
  const ease = (t) => t * t * (3 - 2 * t);
  const easeIn = (t) => t * t * (1.6 - 0.6 * t);

  // ---------- the SVG filter for burning text ----------
  let filter = null;
  function ensureFilter() {
    if (filter) return filter;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.setAttribute("aria-hidden", "true");
    svg.style.position = "absolute";
    svg.innerHTML = `
      <filter id="fb-burn" x="-6%" y="-30%" width="112%" height="160%" color-interpolation-filters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.028" numOctaves="3" seed="4" result="noise"/>
        <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1 0 0 0 0" result="n"/>
        <feComponentTransfer in="n" result="keep"><feFuncA class="fb-keep" type="linear" slope="${KEEP_SLOPE}" intercept="1"/></feComponentTransfer>
        <feComponentTransfer in="n" result="edge"><feFuncA class="fb-edge" type="linear" slope="${KEEP_SLOPE}" intercept="${1 + EMBER_AHEAD}"/></feComponentTransfer>
        <feComposite in="edge" in2="keep" operator="out" result="ring"/>
        <feComposite in="SourceAlpha" in2="ring" operator="in" result="ringGlyph"/>
        <feFlood flood-color="#ff8a1f"/>
        <feComposite in2="ringGlyph" operator="in" result="ember"/>
        <feGaussianBlur in="ember" stdDeviation="4" result="glow"/>
        <feComposite in="SourceGraphic" in2="keep" operator="in" result="text"/>
        <feMerge><feMergeNode in="glow"/><feMergeNode in="text"/><feMergeNode in="ember"/></feMerge>
      </filter>`;
    document.body.appendChild(svg);
    filter = {
      turb: svg.querySelector("feTurbulence"),
      keep: svg.querySelector(".fb-keep"),
      edge: svg.querySelector(".fb-edge"),
    };
    return filter;
  }

  // ---------- sparks: a full-screen canvas of rising embers ----------
  const sparks = { canvas: null, ctx: null, list: [], raf: 0 };
  function sparkLayer(host) {
    if (!host) return;
    if (!sparks.canvas || !sparks.canvas.isConnected) {
      const c = document.createElement("canvas");
      c.className = "fb-sparks";
      c.setAttribute("aria-hidden", "true");
      host.appendChild(c);
      sparks.canvas = c;
      sparks.ctx = c.getContext("2d");
      sparks.canvas.width = 0;
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const c = sparks.canvas;
    if (c.width !== Math.round(innerWidth * dpr)) {
      c.width = Math.round(innerWidth * dpr); c.height = Math.round(innerHeight * dpr);
      sparks.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }
  function addSpark(x, y, power = 1) {
    if (!sparks.ctx) return;
    sparks.list.push({
      x, y, vx: (Math.random() - 0.5) * 0.6 * power, vy: -(0.6 + Math.random() * 1.6) * power,
      life: 0, max: 40 + Math.random() * 50, r: 0.8 + Math.random() * 1.8,
    });
  }
  function tickSparks() {
    const { ctx, list } = sparks;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    ctx.globalCompositeOperation = "lighter";
    for (let i = list.length - 1; i >= 0; i--) {
      const s = list[i];
      s.life++; s.x += s.vx + Math.sin(s.life * 0.15) * 0.3; s.y += s.vy; s.vy *= 0.995;
      if (s.life > s.max) { list.splice(i, 1); continue; }
      const a = 1 - s.life / s.max;
      ctx.fillStyle = `rgba(255,${80 + Math.round(110 * a)},20,${a.toFixed(3)})`;
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r * (0.6 + a), 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
    sparks.raf = list.length ? requestAnimationFrame(tickSparks) : 0;
  }
  function runSparks() { if (sparks.ctx && !sparks.raf) sparks.raf = requestAnimationFrame(tickSparks); }

  // ---------- burn one line of text ----------
  function line(el, ms, sparkHost) {
    return new Promise((resolve) => {
      if (!el || !el.isConnected) { resolve(); return; }
      const f = ensureFilter();
      f.turb.setAttribute("seed", String(1 + Math.floor(Math.random() * 999)));
      el.style.filter = "url(#fb-burn)";
      const box = el.getBoundingClientRect();
      sparkLayer(sparkHost);
      const t0 = performance.now();
      const frame = (now) => {
        const p = Math.min(1, (now - t0) / ms);
        const keep = 1 - ease(p) * 15;
        f.keep.setAttribute("intercept", keep.toFixed(3));
        f.edge.setAttribute("intercept", (keep + EMBER_AHEAD).toFixed(3));
        el.style.transform = `translateY(${(-10 * p).toFixed(1)}px)`;
        if (p < 0.85) {
          for (let k = 0; k < 3; k++) addSpark(box.left + Math.random() * box.width, box.top + box.height * (0.2 + Math.random() * 0.8));
          runSparks();
        }
        if (p < 1) requestAnimationFrame(frame);
        else { el.style.visibility = "hidden"; resolve(); }
      };
      requestAnimationFrame(frame);
    });
  }

  // ---------- burn the page from the centre outward ----------
  function valueNoise(w, h, seed) {
    // a few octaves of smoothed random lattice values, 0..1
    const out = new Float32Array(w * h);
    let amp = 1, total = 0;
    for (let o = 0, cell = 22; o < 4; o++, cell /= 2, amp *= 0.5) {
      const gw = Math.ceil(w / cell) + 2, gh = Math.ceil(h / cell) + 2;
      const g = new Float32Array(gw * gh);
      let s = (seed + o * 7919) % 2147483646 + 1;
      for (let i = 0; i < g.length; i++) { s = (s * 16807) % 2147483647; g[i] = s / 2147483647; }
      for (let y = 0; y < h; y++) {
        const gy = y / cell, y0 = Math.floor(gy), fy = ease(gy - y0);
        for (let x = 0; x < w; x++) {
          const gx = x / cell, x0 = Math.floor(gx), fx = ease(gx - x0);
          const a = g[y0 * gw + x0], b = g[y0 * gw + x0 + 1], c = g[(y0 + 1) * gw + x0], d = g[(y0 + 1) * gw + x0 + 1];
          out[y * w + x] += amp * ((a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy);
        }
      }
      total += amp;
    }
    for (let i = 0; i < out.length; i++) out[i] /= total;
    return out;
  }

  // colour across the rim: e = 0 just burnt (white-hot), e = 1 untouched paper
  const RAMP = [[0, [255, 236, 150]], [0.18, [255, 150, 30]], [0.42, [190, 60, 10]], [0.62, [45, 20, 10]], [0.82, [150, 110, 80]], [1, null]];
  function rimColour(e, paper) {
    for (let i = 1; i < RAMP.length; i++) {
      if (e <= RAMP[i][0]) {
        const [e0, c0] = RAMP[i - 1];
        const c1 = RAMP[i][1] || paper, t = (e - e0) / (RAMP[i][0] - e0);
        return [c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t];
      }
    }
    return paper;
  }

  function page(host, ms, paperHex, sparkHost) {
    return new Promise((resolve) => {
      const paper = [1, 3, 5].map((i) => parseInt(paperHex.slice(i, i + 2), 16));
      const W = Math.ceil(innerWidth / PAGE_SCALE), H = Math.ceil(innerHeight / PAGE_SCALE);
      const c = document.createElement("canvas");
      c.className = "fb-page-fire";
      c.setAttribute("aria-hidden", "true");
      c.width = W; c.height = H;
      const ctx = c.getContext("2d");
      ctx.fillStyle = paperHex;
      ctx.fillRect(0, 0, W, H);                   // starts as plain paper, so swapping it in is invisible
      host.prepend(c);
      sparkLayer(sparkHost);
      const img = ctx.createImageData(W, H);
      const px = img.data;
      const noise = valueNoise(W, H, Math.floor(Math.random() * 1e6));
      // distance from the centre (0..1 at the corners), roughened by noise so the hole is ragged
      const field = new Float32Array(W * H);
      const cx = W / 2, cy = H / 2, maxD = Math.hypot(cx, cy);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const i = y * W + x;
        field[i] = 0.72 * Math.hypot(x - cx, (y - cy) * 1.15) / maxD + 0.28 * noise[i];
      }
      const t0 = performance.now();
      const frame = (now) => {
        const p = Math.min(1, (now - t0) / ms);
        const front = -0.05 + easeIn(p) * (1.1 + RIM);
        let sparksLeft = 8;
        for (let i = 0, j = 0; i < field.length; i++, j += 4) {
          const e = (field[i] - front) / RIM;
          if (e <= 0) { px[j + 3] = 0; continue; }
          const col = e >= 1 ? paper : rimColour(e, paper);
          px[j] = col[0]; px[j + 1] = col[1]; px[j + 2] = col[2];
          px[j + 3] = e < 0.08 ? Math.round(255 * e / 0.08) : 255;
          if (e < 0.12 && sparksLeft > 0 && Math.random() < 0.004) {
            sparksLeft--;
            addSpark((i % W) * PAGE_SCALE, Math.floor(i / W) * PAGE_SCALE, 1.4);
          }
        }
        ctx.putImageData(img, 0, 0);
        runSparks();
        if (p < 1) requestAnimationFrame(frame);
        else resolve();
      };
      requestAnimationFrame(frame);
    });
  }

  window.FireBurn = Object.freeze({ line, page });
})();
