// intro.js: the short "Here's the deal" opening shown before the dashboard.
// Big lines appear word by word on a light panel, then the panel lifts off the page. The
// dashboard loads underneath while it plays. Shown on every load of the page; skipped for shared
// links (#...), sample-data mode, ?intro=0 and automated browsers (the site checks and the video
// recorder). ?intro=1 always shows it.
// The one number here (over 7x) is the raw VIIRS bias on the test years in results/metrics.json
// (+659.69%, so 7.6 times the MODIS count).
(() => {
  const root = document.getElementById("intro");
  if (!root) return;
  const params = new URLSearchParams(location.search);

  const forced = params.get("intro") === "1";
  const skip = params.get("intro") === "0" || params.has("mock") || location.hash.length > 1
    || navigator.webdriver;
  if (skip && !forced) { root.remove(); return; }

  // *word* marks the accent colour; "/" is a line break
  const isSpanish = params.get("lang") === "es";
  const LINES = isSpanish ? [
    "Así está la cosa",
    "Los satélites vigilan / los *incendios* desde 2000",
    "En 2012 llegaron otros nuevos / que ven *más* *de* *7×* *más*",
    "Parece que el fuego / se disparó. *No* *fue* *así.*",
    "Las cámaras cambiaron. / *Arreglamos* *las* *cuentas.*",
    "Un solo registro",
    "Esto es *FireBridge.*",
  ] : [
    "Here's the deal",
    "Satellites have watched / *fires* since 2000",
    "In 2012 new ones showed up / and saw *over* *7×* *more*",
    "So it looks like fire / exploded. *It* *didn't.*",
    "The cameras changed. / *We* *fixed* *the* *math.*",
    "One fair record",
    "This is *FireBridge.*",
  ];
  const SKIP_LABEL = isSpanish ? "Saltar la introducción" : "Skip intro";

  const LOADING_MS = 900, STAGGER_MS = 75, HOLD_MS = 1500, FIRST_HOLD_MS = 1300, OUT_MS = 420, LIFT_MS = 1000;
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

  function finish() {
    if (done) return;
    done = true;
    root.classList.add("lift");
    document.documentElement.classList.remove("intro-on");
    setTimeout(() => root.remove(), LIFT_MS + 100);
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
      if (i === LINES.length - 1) break;                       // the last line rides up with the panel
      line.classList.add("out");
      await wait(OUT_MS);
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
  skipBtn.addEventListener("click", finish);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") finish(); });
  document.documentElement.classList.add("intro-on");
  root.hidden = false;
  play();
})();
