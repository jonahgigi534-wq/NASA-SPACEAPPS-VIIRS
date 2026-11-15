// hero.js: the floating timeline card on the map. It only mirrors what app.js already shows
// (area name, headline numbers, dates), so no number is computed here.
(() => {
  const $ = (id) => document.getElementById(id);
  const text = (id) => ($(id) ? $(id).textContent.trim() : "");
  const ES = document.documentElement.lang === "es";

  function mirror() {
    $("tl-area").textContent = text("area-label") || "…";
    const total = text("kf-total"), pct = text("kf-pct");
    const parts = [];
    if (total && total !== "–") parts.push(`${total} ${text("kf-total-label").toLowerCase()}`);
    if (pct && pct !== "–") parts.push(`${pct} ${ES ? "lo normal" : "normal"}`);
    $("tl-stats").textContent = parts.join(" · ") || " ";
    $("tl-stats").classList.toggle("hot", $("kf-pct").classList.contains("hot"));
    const fmt = (iso) => {
      if (!iso) return "";
      const d = new Date(iso + "T00:00:00Z");
      return d.toLocaleDateString(ES ? "es" : "en-US", { month: "short", year: "numeric", timeZone: "UTC" });
    };
    $("tl-from").textContent = fmt($("start").value);
    $("tl-to").textContent = fmt($("end").value);
  }
  const watch = new MutationObserver(mirror);
  ["area-label", "kf-total", "kf-pct", "kf-total-label", "range-label"].forEach((id) => {
    if ($(id)) watch.observe($(id), { childList: true, characterData: true, subtree: true, attributes: true });
  });

  // slider: fill the track up to the thumb, and mark the play button while playing
  const slider = $("map-month"), play = $("map-play");
  function paint() {
    const max = +slider.max || 1;
    slider.style.setProperty("--fill", `${(100 * +slider.value) / max}%`);
    play.classList.toggle("playing", play.textContent.trim() !== "▶");
  }
  slider.addEventListener("input", paint);
  new MutationObserver(paint).observe($("map-month-label"), { childList: true, characterData: true, subtree: true });
  new MutationObserver(paint).observe(play, { childList: true, characterData: true, subtree: true });

  mirror();
  paint();
})();
