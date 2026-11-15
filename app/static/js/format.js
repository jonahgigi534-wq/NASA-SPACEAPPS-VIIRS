// format.js: numbers, dates and colors shared by every chart.
const FMT = (() => {
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"];
  const MON = MONTHS.map((m) => m.slice(0, 3));

  const int = (v) => (v == null || isNaN(v)) ? "–" : Math.round(v).toLocaleString("en-US");

  // % of median, readable even when it's huge: 312% -> "312%", 1155% -> "11.6×"
  function pct(p) {
    if (p == null || isNaN(p)) return "–";
    if (p >= 1000) return `${(p / 100).toFixed(p >= 10000 ? 0 : 1)}×`;
    return `${Math.round(p)}%`;
  }
  function pctSub(p) {
    if (p == null || isNaN(p)) return "no normal to compare with";
    return p >= 1000 ? "the median (normal)" : "of the median (normal)";
  }
  const monthLabel = (ym) => { // "2011-04" -> "Apr 2011"
    if (!ym) return "–";
    const [y, m] = ym.split("-").map(Number);
    return `${MON[m - 1]} ${y}`;
  };
  const mmdd = (s) => { // "03-15" -> "Mar 15"
    if (!s) return "";
    const [m, d] = s.split("-").map(Number);
    return `${MON[m - 1]} ${d}`;
  };
  const date = (iso) => { // "2011-04-01" -> "Apr 1, 2011"
    const [y, m, d] = iso.split("-").map(Number);
    return `${MON[m - 1]} ${d}, ${y}`;
  };
  const iso = (d) => d.toISOString().slice(0, 10);
  // ISO weeks (Monday to Sunday; week 1 holds January 4)
  function isoMonday(year, week) {
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const mon1 = new Date(jan4); mon1.setUTCDate(4 - ((jan4.getUTCDay() + 6) % 7));
    const d = new Date(mon1); d.setUTCDate(mon1.getUTCDate() + (week - 1) * 7);
    return d;
  }
  function isoWeekOf(d) {                     // Date -> [isoYear, week]
    const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
    t.setUTCDate(t.getUTCDate() + 3 - ((t.getUTCDay() + 6) % 7));   // Thursday of this week
    const y = t.getUTCFullYear();
    return [y, 1 + Math.round((t - isoMonday(y, 1)) / 6048e5 - 3 / 7)];
  }
  const weekRange = (year, week) => {        // "Apr 4 – Apr 10"
    const m = isoMonday(year, week), s = new Date(m); s.setUTCDate(m.getUTCDate() + 6);
    const f = (d) => `${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
    return `${f(m)} – ${f(s)}`;
  };

  // ---- colors (colorblind-safe) ----
  // counts: viridis on a log scale (log(1 + count)), so ordinary fire seasons stay visible
  // next to record months that are 10-100x bigger
  // The scale starts at `lo` (the quietest ~5% of months), not 0, so typical months spread over
  // the whole ramp; anything at or below lo gets the darkest color.
  function countPos(v, max, lo = 0) {
    const a = Math.log1p(Math.max(0, lo)), b = Math.log1p(Math.max(lo + 1, max));
    return Math.max(0, Math.min(1, (Math.log1p(Math.max(0, v)) - a) / (b - a)));
  }
  function countAt(t, max, lo = 0) {
    const a = Math.log1p(Math.max(0, lo)), b = Math.log1p(Math.max(lo + 1, max));
    return Math.expm1(a + t * (b - a));
  }
  function countScale(max, lo = 0) {
    const s = (v) => d3.interpolateViridis(countPos(v, max, lo));
    return s;
  }
  // anomaly: purple (below normal) - white - orange (above normal), log scale of value/median
  function anomalyColor(value, median) {
    if (value == null) return null;
    if (!median || median <= 0) return value > 0 ? d3.interpolatePuOr(0.92) : "#f2f2f2";
    const r = Math.log10(Math.max(value, 0.01) / median);         // 0 = normal, +1 = 10x
    const t = 0.5 + Math.max(-1, Math.min(1, r)) / 2;              // d3 PuOr: 0 purple ... 1 orange
    return d3.interpolatePuOr(t);                                  // more fire = orange (warm)
  }
  const MISSING = "#b9b9b9";
  const ink = "#1d1f22";

  // readable text color on a given background
  function textOn(bg) {
    const c = d3.color(bg);
    if (!c) return ink;
    const { r, g, b } = c.rgb();
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? ink : "#fff";
  }

  return { MONTHS, MON, int, pct, pctSub, monthLabel, mmdd, date, iso, isoMonday, isoWeekOf, weekRange,
           countScale, countPos, countAt, anomalyColor,
           MISSING, textOn, ink };
})();
