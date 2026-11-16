// help.js: plain-language help for people who have never seen fire data before (the judges).
// Adds small "?" buttons next to the key figures and settings. Each opens a short dark card
// (the design kit's info popover) saying what the thing means in everyday words.
// No numbers here: every figure on the page comes from the API.
(() => {
  const TIPS = [
    { at: "#kf-total", title: "The big number",
      text: "How many fire hotspots satellites spotted inside your area between your dates. A hotspot is one small patch of ground that was hot enough to be burning when a satellite passed over. One big fire makes many hotspots." },
    { at: "#kf-pct", title: "Compared with normal",
      text: "Your number divided by a normal year for the same dates. 1× means a normal amount of fire, 2× means twice the usual, and below 1× means quieter than usual.",
      tech: "Normal is the median (the middle value) of the same dates across the baseline years shown under the title." },
    { at: "#kf-month", title: "Busiest month",
      text: "The month inside your dates when satellites saw the most fire here." },
    { at: "#kf-year", title: "Busiest year",
      text: "The year on record with the most fire in this area." },
    { at: "#kf-season", title: "Fire season",
      text: "The months when this area usually burns, worked out from every past year, and the day it usually peaks." },
    { at: "#mode-label", title: "Which satellite record?",
      text: "Two satellite cameras watch for fire. The older one (MODIS) has watched since 2000. A newer, sharper one (VIIRS) arrived in 2012 and sees many more small fires, so raw counts jump even when fire did not. Harmonized translates the new camera onto the old camera's scale so 2001 to today is one fair record. Start with Harmonized.",
      tech: "MODIS only and Raw VIIRS show each camera on its own, without the fix." },
    { at: "#metric-label", title: "Count or fire power?",
      text: "Hotspot count is how many burning spots were seen. Fire power is how much heat the fires gave off, so it tells a few huge fires apart from many small ones." },
  ];

  let open = null;
  function close() {
    if (!open) return;
    open.btn.setAttribute("aria-expanded", "false");
    open.pop.hidden = true;
    open = null;
  }

  function popover(tip, id) {
    const pop = document.createElement("span");
    pop.className = "fb-pop";
    pop.id = id;
    pop.setAttribute("role", "note");
    pop.hidden = true;
    const b = document.createElement("b");
    b.textContent = tip.title;
    const p = document.createElement("span");
    p.className = "fb-pop-text";
    p.textContent = tip.text;
    pop.append(b, p);
    if (tip.tech) {
      const t = document.createElement("span");
      t.className = "fb-pop-tech";
      t.textContent = tip.tech;
      pop.appendChild(t);
    }
    return pop;
  }

  function build(tip, i) {
    const target = document.querySelector(tip.at);
    if (!target) return;
    const host = target.closest(".kf") || target;
    const wrap = document.createElement("span");
    wrap.className = "fb-info" + (host.classList.contains("kf") ? " fb-info-kf" : "");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fb-info-btn";
    btn.textContent = "?";
    btn.setAttribute("aria-label", `What does this mean: ${tip.title}`);
    btn.setAttribute("aria-expanded", "false");
    const pop = popover(tip, `fb-pop-${i}`);
    btn.setAttribute("aria-controls", pop.id);
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = open && open.btn === btn;
      close();
      if (wasOpen) return;
      btn.setAttribute("aria-expanded", "true");
      pop.hidden = false;
      open = { btn, pop };
    });
    wrap.append(btn, pop);
    host.appendChild(wrap);
  }

  TIPS.forEach(build);
  document.addEventListener("click", (e) => { if (open && !open.pop.contains(e.target)) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !open) return;
    const btn = open.btn;
    close();
    btn.focus();
  });
})();
