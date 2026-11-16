"""
Capture real footage of the live FireBridge site for the demo reel (video/reel.html).

Drives the deployed site with Playwright at 1920x1080 and saves a sharp screenshot of every real
app state the reel shows, plus the on-screen boxes of the elements the camera moves to.
Nothing is mocked: every frame is the live site.

    python video/capture.py --url https://<live site>/
Writes video/assets/*.png, video/assets/rects.json and video/assets/timeseries.json.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "assets"
BBOX = [-107, 25, -100, 36]
AREA = "area=bbox%3A-107%2C25%2C-100%2C36&label=West+Texas+and+northern+Mexico%2C+{label}"
COMMON = "&base=2003-2022&mode=harmonized&cal=counts&gran=month&metric=count"


def hash_for(start, end, label, tab="calendar"):
    return "#" + AREA.format(label=label) + f"&start={start}&end={end}" + COMMON + f"&tab={tab}"


def rect(page, sel):
    return page.evaluate(
        """(s) => { const e = document.querySelector(s); if (!e) return null;
                    const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }""", sel)


def settle(page, ms=2500):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/") + "/"
    OUT.mkdir(exist_ok=True)
    rects = {}

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)

        def shot(name, **sels):
            pg.screenshot(path=str(OUT / f"{name}.png"))
            rects[name] = {k: rect(pg, s) for k, s in sels.items()}
            print("saved", name)

        # ---- 1. the map: preset area, fire layer off -> on -> vs normal ----------------------
        pg.goto(base + hash_for("2011-04-01", "2011-07-31", "Apr-Jul+2011"), timeout=180000)
        pg.wait_for_function("document.getElementById('kf-total') && document.getElementById('kf-total').textContent !== '–'",
                             timeout=180000)
        settle(pg, 6000)
        pg.click("label:has(input[value=off])")
        settle(pg)
        shot("map_off", hotspots="label:has(input[value=counts])", panel=".tl-card, #tl-area",
             presets="#preset-buttons")
        pg.click("label:has(input[value=counts])")
        settle(pg, 4000)
        area_box = pg.evaluate("""() => {
            const ps = [...document.querySelectorAll('.leaflet-overlay-pane path')];
            let best = null;
            for (const p of ps) { const r = p.getBoundingClientRect(); const s = getComputedStyle(p).stroke;
              if (r.width > 200 && (!best || r.width * r.height < best[2] * best[3]) && !p.getAttribute('stroke-dasharray'))
                best = [r.x, r.y, r.width, r.height]; }
            return best; }""")
        shot("map_on", hotspots="label:has(input[value=counts])", stats="#tl-stats", play="#map-play",
             unusual="#unusual")
        rects["map_on"]["area"] = area_box
        pg.click("label:has(input[value=anomaly])")
        settle(pg, 4000)
        shot("map_anom", unusual="#unusual", unusual_first="#unusual-list .preset", legend=".leaflet-bottom.leaflet-left")
        pg.click("label:has(input[value=counts])")
        settle(pg, 2000)

        # ---- 2. month-by-month replay over all of 2011 --------------------------------------
        pg.goto(base + hash_for("2011-01-01", "2011-12-31", "2011"))
        pg.reload()
        pg.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=180000)
        settle(pg, 6000)
        n = int(pg.evaluate("document.getElementById('map-month').max"))
        for i in range(1, n + 1):
            pg.evaluate("""(i) => { const s = document.getElementById('map-month'); s.value = String(i);
                                    s.dispatchEvent(new Event('input', {bubbles: true})); }""", i)
            pg.wait_for_timeout(400)
            settle(pg, 1800)
            pg.evaluate("document.getElementById('map-play').textContent = '⏸'")   # looks like it's playing
            shot(f"replay_{i:02d}", play="#map-play", label="#map-month-label")
        print("replay frames:", n)

        # ---- 3. full analysis: key figures + burning calendar -------------------------------
        pg.goto(base + hash_for("2011-04-01", "2011-07-31", "Apr-Jul+2011"))
        pg.reload()
        pg.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=180000)
        settle(pg, 5000)
        top = pg.evaluate("document.getElementById('results-title').getBoundingClientRect().top + scrollY")
        pg.evaluate(f"window.scrollTo(0, {top - 24})")
        settle(pg, 1500)
        cal_cell = pg.evaluate("""() => {           // the highlighted 2011 cells ("your dates")
            const rs = [...document.querySelectorAll('#calendar svg rect')].filter(r => {
              const s = r.getAttribute('stroke'); return s && s !== 'none' && +r.getAttribute('stroke-width') >= 2; });
            if (!rs.length) return null;
            const bs = rs.map(r => r.getBoundingClientRect());
            const x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
            return [x0, y0, Math.max(...bs.map(b => b.right)) - x0, Math.max(...bs.map(b => b.bottom)) - y0]; }""")
        shot("analysis", kf="#key-figures", summary="#summary-text", calendar="#calendar",
             kf_pct="#kf-pct", title="#results-title")
        rects["analysis"]["cal_2011"] = cal_cell

        # ---- 4. now vs history, fires vs past ------------------------------------------------
        for tab, name, sels in (("now", "now", {"panel": "#panel-now"}),
                                ("fires", "fires", {"panel": "#panel-fires", "latest": "#fires-latest"})):
            pg.click(f"#tab-{tab}")
            pg.wait_for_timeout(1500)
            settle(pg, 4000 if tab == "fires" else 2500)
            tabs_top = pg.evaluate("document.getElementById('tab-calendar').getBoundingClientRect().top + scrollY")
            pg.evaluate(f"window.scrollTo(0, {tabs_top - 120})")
            settle(pg, 1200)
            shot(name, **sels)

        # ---- 5. downloads ---------------------------------------------------------------------
        top = pg.evaluate("document.getElementById('settings').getBoundingClientRect().top + scrollY")
        pg.evaluate(f"window.scrollTo(0, {top - 200})")
        settle(pg, 800)
        shot("downloads", settings="#settings", csv="#dl-hotspots", geojson="#dl-geojson", kml="#dl-kml")

        # ---- data for the animated "satellite switch" chart ----------------------------------
        ts = pg.evaluate("""async (bbox) => {
            const r = await fetch('/api/timeseries', {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({area: {type: 'bbox', bbox}, start: '2011-04-01', end: '2011-07-31',
                                    baseline: [2003, 2022], mode: 'harmonized', metric: 'count', lang: 'en'})});
            return r.json(); }""", BBOX)
        (OUT / "timeseries.json").write_text(json.dumps(ts))
        summ = pg.evaluate("""async (bbox) => {
            const r = await fetch('/api/summary', {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({area: {type: 'bbox', bbox}, start: '2011-04-01', end: '2011-07-31',
                                    baseline: [2003, 2022], mode: 'harmonized', metric: 'count', lang: 'en'})});
            return r.json(); }""", BBOX)
        (OUT / "summary.json").write_text(json.dumps(summ))
        b.close()

    (OUT / "rects.json").write_text(json.dumps(rects, indent=1))
    print("done")


if __name__ == "__main__":
    main()
