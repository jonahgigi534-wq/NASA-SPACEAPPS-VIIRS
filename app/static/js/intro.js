// intro.js: the short "Here's the deal" opening shown before the dashboard.
// Big lines appear word by word on a light panel. Each old line burns away (js/burn.js) before
// the next one, and at the end the whole page burns from the centre outward to reveal the globe
// ("Where do you want to look?") underneath. The dashboard loads underneath while it plays. Shown on every load and every reload. Skipped when
// someone opens a shared link (#...) fresh, but not when they reload one: the app writes the
// current view into #... itself, so every reload has one. Also skipped in sample-data mode, with
// ?intro=0 and in automated browsers (the site checks and the video recorder). ?intro=1 forces it.
// The one number here (over 7x) is the raw VIIRS bias on the test years in results/metrics.json
// (+659.69%, so 7.6 times the MODIS count).
(() => {
  const root = document.getElementById("intro");
  if (!root) return;
  const params = new URLSearchParams(location.search);

  const forced = params.get("intro") === "1";
  const nav = (performance.getEntriesByType && performance.getEntriesByType("navigation")[0]) || {};
  const openedSharedLink = location.hash.length > 1 && nav.type !== "reload";
  const skip = params.get("intro") === "0" || params.has("mock") || openedSharedLink
    || navigator.webdriver;
  if (skip && !forced) { root.remove(); return; }
  window.FireBridgeIntro = true;                 // js/globe.js opens the globe underneath when the story plays

  // *word* marks the accent colour; "/" is a line break
  const LINES = [
    "Here's the deal",
    "Satellites have watched / *fires* since 2000",
    "In 2012 new ones showed up / and saw *over* *7×* *more*",
    "So it looks like fire / exploded. *It* *didn't.*",
    "The cameras changed. / *We* *fixed* *the* *math.*",
    "One fair record",
    "This is *FireBridge.*",
  ];
  const SKIP_LABEL = "Skip intro";

  const LOADING_MS = 900, STAGGER_MS = 75, HOLD_MS = 1500, FIRST_HOLD_MS = 1300, OUT_MS = 420;
  const LINE_BURN_MS = 900, PAGE_BURN_MS = 1800, SKIP_BURN_MS = 1000, FADE_MS = 450, PAPER = "#f7f7f7";
  const calm = !window.FireBurn || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const panel = root.querySelector(".intro-panel");
  const stage = root.querySelector(".intro-stage");
  const loading = root.querySelector(".intro-loading");
  const skipBtn = root.querySelector(".intro-skip");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  let done = false;

  function buildLine(text, i) {
    const p = document.createElement("p");
    p.className = "intro-line" + (i === 0 ? " first" : i === LINES.length - 1 ? " last" : "");
    p.setAttribute("aria-hidden", "true");
    text.split(" ").forEach((tok) => {
      if (tok === "/") { p.appendChild(document.createElement("br")); return; }
      const hot = /^\*.*\*$/.test(tok);
      const w = document.createElement("span");
      w.className = "w" + (hot ? " hot" : "");
      w.textContent = (hot ? tok.slice(1, -1) : tok) + " ";
      p.appendChild(w);
    });
    return p;
  }

  // the old line burns away (or just fades, with reduced motion)
  function burnLine(line) {
    line.classList.add("burnt");
    if (calm) { line.classList.add("out"); return wait(OUT_MS); }
    return FireBurn.line(line, LINE_BURN_MS, root);
  }

  // the end: the page catches fire in the middle and burns outward, leaving the globe
  async function finish(skipped) {
    if (done) return;
    done = true;
    document.documentElement.classList.remove("intro-on");
    root.classList.add("burning");
    if (calm) { root.classList.add("fade"); setTimeout(() => root.remove(), FADE_MS + 100); return; }
    const burnMs = skipped === true ? SKIP_BURN_MS : PAGE_BURN_MS;
    const fallback = setTimeout(() => root.remove(), burnMs + 3000);   // in case frames stop (hidden tab)
    const current = stage.querySelector(".intro-line:not(.burnt)");
    if (current) { burnLine(current); await wait(skipped === true ? 120 : 300); }
    const burning = FireBurn.page(panel, burnMs, PAPER, root);
    panel.classList.add("on-fire");              // the canvas now draws the paper; the panel goes clear
    await burning;
    clearTimeout(fallback);
    root.remove();
  }

  async function play() {
    await wait(LOADING_MS);
    loading.classList.add("out");
    await wait(300);
    for (let i = 0; i < LINES.length && !done; i++) {
      const line = buildLine(LINES[i], i);
      stage.appendChild(line);
      const words = [...line.querySelectorAll(".w")];
      void line.offsetWidth;                                   // start the transitions from the hidden state
      words.forEach((w, k) => setTimeout(() => w.classList.add("in"), k * STAGGER_MS));
      await wait(words.length * STAGGER_MS + (i === 0 ? FIRST_HOLD_MS : HOLD_MS));
      if (i === LINES.length - 1) break;                       // the last line burns with the page
      await burnLine(line);
      line.remove();
    }
    finish();
  }

  // the same story as plain text for screen readers (the animated lines are aria-hidden)
  const sr = document.createElement("p");
  sr.className = "sr-only";
  sr.textContent = LINES.map((l) => l.replace(/[*/]/g, "").replace(/\s+/g, " ")).join(". ") + ".";
  root.appendChild(sr);

  skipBtn.textContent = SKIP_LABEL;
  skipBtn.addEventListener("click", () => finish(true));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") finish(true); });
  document.documentElement.classList.add("intro-on");
  root.hidden = false;
  play();
})();
