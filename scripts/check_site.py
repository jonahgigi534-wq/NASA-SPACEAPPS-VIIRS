"""
Click through the whole FireBridge site with Playwright and check every feature and download:
draw tools, typed coordinates, presets, dates, baseline, modes, calendar drill-down (mouse and
keyboard), tabs, all PNG downloads, both CSVs, the Methods page, ?mock=1 and the phone layout.

    python scripts/check_site.py http://localhost:8000
    python scripts/check_site.py https://<space>.hf.space            # the live site
    python scripts/check_site.py http://localhost:8000 docs/screenshots   # also save screenshots
Exits 1 if any check fails. Needs: pip install playwright (Chromium, or Edge on Windows).
"""
import csv, io, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
TMP = None
if len(sys.argv) > 2:
    SHOTS = Path(sys.argv[2])
else:                                   # no screenshot folder given: throw them away
    import tempfile
    TMP = tempfile.TemporaryDirectory()
    SHOTS = Path(TMP.name)
SHOTS.mkdir(parents=True, exist_ok=True)
results, errors = [], []

def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

def wait_idle(page, t=15000):
    page.wait_for_function("document.getElementById('loading').hidden", timeout=t)
    page.wait_for_timeout(300)

def area_label(page): return page.inner_text("#area-label")

with sync_playwright() as p:
    try:
        browser = p.chromium.launch()
    except Exception:
        browser = p.chromium.launch(channel="msedge")
    ctx = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE + "/")
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=30000)
    wait_idle(page)
    ok("loads with first preset", "West Texas" in area_label(page), page.inner_text("#kf-total"))
    ok("calendar drawn", page.locator("#calendar .cal-cell").count() > 300, str(page.locator("#calendar .cal-cell").count()))
    page.screenshot(path=SHOTS / "01_overview.png", full_page=True)

    # ---- draw tools --------------------------------------------------------------------------
    m = page.locator("#map").bounding_box()
    cx, cy = m["x"] + m["width"] / 2, m["y"] + m["height"] / 2
    page.click(".leaflet-draw-draw-rectangle")
    page.mouse.move(cx - 40, cy - 30); page.mouse.down(); page.mouse.move(cx + 20, cy + 25, steps=8); page.mouse.up()
    wait_idle(page)
    ok("draw rectangle", area_label(page) == "Your box", page.inner_text("#summary-text")[:80])

    page.click(".leaflet-draw-draw-polygon")
    for dx, dy in [(-30, -20), (30, -25), (20, 30)]:
        page.mouse.click(cx + dx, cy + dy); page.wait_for_timeout(150)
    page.mouse.click(cx - 30, cy - 20)
    wait_idle(page)
    ok("draw polygon", area_label(page) == "Your polygon", page.inner_text("#kf-total"))

    page.click(".leaflet-draw-draw-circle")
    page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 25, cy, steps=6); page.mouse.up()
    wait_idle(page)
    ok("draw circle (point + radius)", area_label(page) == "Your circle", page.inner_text("#kf-total"))

    # ---- typed coordinates ------------------------------------------------------------------
    page.click("details.coords summary")
    page.click("#bbox-form button"); wait_idle(page)
    ok("typed box", area_label(page).startswith("Box "), page.inner_text("#kf-total"))
    page.click("#point-form button"); wait_idle(page)
    ok("typed point + radius", "km around" in area_label(page), page.inner_text("#kf-total"))
    page.fill("#bbox-form [name=w]", "0"); page.fill("#bbox-form [name=s]", "40")
    page.fill("#bbox-form [name=e]", "10"); page.fill("#bbox-form [name=n]", "50")
    page.click("#bbox-form button"); wait_idle(page)
    ok("area outside regions -> plain error", "outside the regions" in page.inner_text("#error-banner"),
       page.inner_text("#error-banner")[:80])

    # ---- presets ------------------------------------------------------------------------------
    n = page.locator("#preset-buttons .preset").count()
    for i in range(n):
        page.locator("#preset-buttons .preset").nth(i).click(); wait_idle(page)
        ok(f"preset {i + 1}", page.locator("#preset-buttons .preset").nth(i).get_attribute("aria-pressed") == "true"
           and page.is_hidden("#error-banner"), f"{area_label(page)} -> {page.inner_text('#kf-pct')}")
    page.locator("#preset-buttons .preset").nth(0).click(); wait_idle(page)

    # ---- dates, baseline, modes -------------------------------------------------------------
    page.fill("#start", "2011-03-01"); page.fill("#end", "2011-05-31"); page.dispatch_event("#end", "change")
    page.wait_for_timeout(600); wait_idle(page)
    ok("date range", "Mar 1, 2011" in page.inner_text("#range-label"), page.inner_text("#range-label")[:40])
    for r in ["12m", "ytd", "all"]:
        page.click(f'[data-range="{r}"]'); wait_idle(page)
    ok("quick ranges", "Jan 1, 2001" in page.inner_text("#range-label") and page.is_hidden("#error-banner"))
    page.locator("#preset-buttons .preset").nth(0).click(); wait_idle(page)
    page.fill("#base0", "2005"); page.dispatch_event("#base0", "change"); page.wait_for_timeout(700); wait_idle(page)
    ok("baseline years", "2005–2022" in page.inner_text("#range-label"))
    page.fill("#base0", "2003"); page.dispatch_event("#base0", "change"); page.wait_for_timeout(700); wait_idle(page)
    for mode in ["modis_only", "viirs_raw", "harmonized"]:
        page.check(f"input[name=mode][value={mode}]", force=True); wait_idle(page)
        ok(f"mode {mode}", page.is_hidden("#error-banner"), f"{page.inner_text('#kf-total')} / {page.inner_text('#kf-pct')}")

    # ---- calendar: anomaly view, month drill-down, keyboard ----------------------------------
    page.check("input[name=calview][value=anomaly]", force=True); page.wait_for_timeout(300)
    page.screenshot(path=SHOTS / "02_calendar_vs_normal.png", full_page=False, clip=page.locator("#panel-calendar").bounding_box())
    page.check("input[name=calview][value=counts]", force=True)
    page.locator('.cal-cell[data-period="2011-04"]').click(); wait_idle(page)
    ok("click month -> daily calendar", page.is_visible("#daily-card") and page.locator("#daily svg g[role=img]").count() == 30)
    page.locator("#daily-card").screenshot(path=SHOTS / "03_daily.png")
    page.locator('.cal-cell[data-period="2011-06"]').focus()
    page.keyboard.press("ArrowUp"); page.keyboard.press("Enter"); wait_idle(page)
    ok("keyboard: arrow + Enter opens a month", "May 2011" in page.inner_text("#daily-title"), page.inner_text("#daily-title"))

    # ---- downloads (PNG of every chart, both CSVs) --------------------------------------------
    def png(btn_selector, label):
        with page.expect_download(timeout=15000) as d:
            page.click(btn_selector)
        data = Path(d.value.path()).read_bytes()
        ok(f"PNG {label}", data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 5000, f"{d.value.suggested_filename}, {len(data) // 1024} KB")
    png('[data-png="calendar-svg"]', "burning calendar")
    png('[data-png="daily-svg"]', "daily calendar")
    png('[data-png="chart-longterm"]', "long-term chart")
    page.click("#tab-patterns"); page.wait_for_timeout(500)
    ok("patterns tab", page.inner_text("#season-text").startswith("Fire season"), page.inner_text("#season-text")[:70])
    page.locator("#panel-patterns").screenshot(path=SHOTS / "04_patterns.png")
    png('[data-png="chart-months"]', "monthly chart")
    png('[data-png="chart-years"]', "yearly chart")
    page.click("#tab-now"); page.wait_for_timeout(500)
    ok("now vs history tab", "so far" in page.inner_text("#now-text"), page.inner_text("#now-text")[:90])
    page.locator("#panel-now").screenshot(path=SHOTS / "05_now_vs_history.png")
    png('[data-png="chart-now"]', "this-month chart")
    png('[data-png="now-daily-svg"]', "this-month daily")
    page.keyboard.press("Tab")
    page.focus("#tab-now"); page.keyboard.press("ArrowLeft")
    ok("keyboard: arrow keys move between tabs", page.get_attribute("#tab-patterns", "aria-selected") == "true")
    page.click("#tab-calendar")

    def csvdl(btn, cols, label):
        with page.expect_download(timeout=60000) as d:
            page.click(btn)
        text = Path(d.value.path()).read_text(encoding="utf-8")
        rows = list(csv.reader(io.StringIO("\n".join(l for l in text.splitlines() if not l.startswith("#")))))
        ok(f"CSV {label}", rows and rows[0] == cols and len(rows) > 1, f"{d.value.suggested_filename}, {len(rows) - 1} rows")
    csvdl("#dl-hotspots", ["lat", "lon", "datetime_utc", "satellite", "sensor", "frp", "confidence", "daynight", "provisional", "weight"], "hotspots")
    csvdl("#dl-series", ["date", "value", "median", "mean", "std", "z", "pct_of_median", "source_sensor", "provisional_flag", "missing_flag"], "analytics")

    # ---- fire on the map ----------------------------------------------------------------------
    page.wait_for_function("document.querySelector('.map-legend') && document.querySelector('.map-legend').style.display !== 'none'", timeout=15000)
    ok("fire on the map (legend + layer)", page.locator(".leaflet-overlay-pane canvas").count() >= 1,
       page.inner_text(".map-legend")[:60])
    page.evaluate("const s = document.getElementById('map-month'); s.value = '1'; s.dispatchEvent(new Event('input'))")
    page.wait_for_timeout(1500)
    ok("map month slider", page.inner_text("#map-month-label") != "All selected dates", page.inner_text("#map-month-label"))
    page.evaluate("const s = document.getElementById('map-month'); s.value = '0'; s.dispatchEvent(new Event('input'))")

    # ---- unusual right now + compare ----------------------------------------------------------
    if page.is_visible("#unusual"):
        t = page.locator("#unusual-list .preset").first.inner_text()
        page.locator("#unusual-list .preset").first.click(); wait_idle(page)
        shown = t.split("\n")[1].split(" hotspots")[0]
        ok("unusual right now: click analyzes that square", page.inner_text("#kf-total") == shown,
           f"panel {shown} vs analysis {page.inner_text('#kf-total')}")
        page.locator("#preset-buttons .preset").nth(0).click(); wait_idle(page)
    page.locator("#compare summary").click()
    page.fill("#cmp-start", "2022-04-01"); page.fill("#cmp-end", "2022-07-31")
    page.click("#compare-form button"); wait_idle(page)
    ok("compare with another period", page.is_visible("#compare-table") and "Other period" in page.inner_text("#compare-table"),
       page.inner_text("#compare-table").split("\n")[-1][:60])

    # ---- fires vs past fires --------------------------------------------------------------------
    page.click("#tab-fires")
    page.wait_for_function("document.querySelectorAll('#fires-largest tbody tr').length > 0", timeout=30000)
    ok("fires vs past fires (clusters ranked)", "largest of" in page.inner_text("#fires-text"), page.inner_text("#fires-text")[:90])
    before = page.input_value("#start")
    page.locator('#fires-largest [data-fire="g0"]').click(); wait_idle(page)
    ok("show a past fire (dates jump to it)", page.input_value("#start") != before,
       page.inner_text("#range-label")[:40])
    page.click("#tab-calendar")
    page.locator("#preset-buttons .preset").nth(0).click(); wait_idle(page)

    # ---- GeoJSON / KML, shareable link, weeks, fire power, place search, briefing ------------
    for btn, label, magic in [("#dl-geojson", "GeoJSON", b'{"type":"FeatureCollection"'), ("#dl-kml", "KML", b"<?xml")]:
        with page.expect_download(timeout=60000) as d:
            page.click(btn)
        data = Path(d.value.path()).read_bytes()
        ok(f"{label} hotspots", data.startswith(magic) and len(data) > 1000, f"{d.value.suggested_filename}, {len(data) // 1024} KB")
    link = page.url
    ok("shareable link in the address", "#area=" in link)
    page.check("input[name=calgran][value=week]", force=True); wait_idle(page)
    ok("weekly calendar", page.locator("#calendar .cal-cell").count() > 1000, str(page.locator("#calendar .cal-cell").count()))
    page.check("input[name=calgran][value=month]", force=True); wait_idle(page)
    page.click("#tab-patterns"); page.wait_for_timeout(300)
    ok("high-risk weeks + trend", page.inner_text("#weeks-text").startswith("Highest-risk weeks")
       and page.inner_text("#trend-text").startswith("Long-term trend"), page.inner_text("#trend-text")[:80])
    page.click("#tab-calendar")
    page.check("input[name=metric][value=frp]", force=True); wait_idle(page)
    ok("fire power (FRP) measure", "fire power" in page.inner_text("#kf-total-label").lower()
       and page.is_disabled("input[name=mode][value=viirs_raw]"), page.inner_text("#kf-total"))
    page.check("input[name=metric][value=count]", force=True); wait_idle(page)
    p2 = ctx.new_page()
    p2.goto(link)
    p2.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=30000)
    p2.wait_for_timeout(800)
    ok("shareable link reopens the same view", p2.inner_text("#area-label") == area_label(page), p2.inner_text("#area-label"))
    p2.close()
    page.fill("#place-q", "Lubbock, Texas"); page.click("#place-form button")
    try:
        page.wait_for_selector("#place-results li button", timeout=15000)
        page.locator("#place-results li button").first.click(); wait_idle(page)
        ok("place search (OpenStreetMap)", area_label(page).startswith("50 km around"), area_label(page))
    except Exception as ex:
        ok("place search (OpenStreetMap)", False, f"no results: {ex}"[:120])
    # the briefing as a real PDF (US Letter), the way the browser prints it: must be one page
    page.evaluate("window.FireBridgeBriefing.prepare()")
    page.wait_for_timeout(300)
    pdf = page.pdf(format="Letter", print_background=True)
    (SHOTS / "08_briefing.pdf").write_bytes(pdf)
    page.evaluate("window.FireBridgeBriefing.end()")
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    ok("briefing prints on one page", pages == 1, f"{pages} page(s), {len(pdf) // 1024} KB")

    # ---- accessibility audit (axe-core): no serious or critical problems ----------------------
    def axe(pg, label):
        pg.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js")
        v = pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
                        ".filter(x => ['serious', 'critical'].includes(x.impact))"
                        ".map(x => x.id + ' (' + x.nodes.length + ')')")
        ok(f"accessibility audit: {label}", not v, ", ".join(v)[:200])
    axe(page, "main page")

    # ---- methods page, mock mode, phone ------------------------------------------------------
    page.click("text=How it works"); page.wait_for_load_state("networkidle")
    ok("methods page", page.locator("table").count() >= 3 and page.locator("figure img").count() >= 6,
       page.title())
    page.screenshot(path=SHOTS / "06_methods.png", full_page=False)
    axe(page, "methods page")
    page.goto(BASE + "/?mock=1")
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=20000)
    ok("mock mode (?mock=1)", page.is_visible("#mock-banner"))

    # opening story: automated browsers skip it (so every check above ran without it); ?intro=1
    # shows it, and Skip takes it away
    page.goto(BASE + "/?intro=1")
    page.wait_for_selector(".intro-line .w.in", timeout=10000)
    intro_text = page.inner_text(".intro-line")
    page.click(".intro-skip")
    page.wait_for_selector("#intro", state="detached", timeout=5000)
    ok("opening story (?intro=1) shows and can be skipped", "deal" in intro_text.lower(), intro_text)

    # opening globe: ?globe=1 shows the region choices; picking one loads that region and the globe leaves
    page.goto(BASE + "/?globe=1")
    page.wait_for_selector(".globe-choice", timeout=30000)
    n_choices = page.locator(".globe-choice").count()
    region_name = page.inner_text(".globe-choice >> nth=0")
    page.wait_for_function("window.FireBridgeApp", timeout=30000)
    page.click(".globe-choice >> nth=0")
    page.wait_for_function("document.getElementById('globe').hidden", timeout=15000)
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=30000)
    ok("opening globe (?globe=1): pick a region", n_choices == 3 and area_label(page) == region_name,
       f"{n_choices} regions, chose {area_label(page)}")
    wheel_before = page.evaluate("MAP.view().zoom")
    page.mouse.move(500, 400); page.mouse.wheel(0, -300); page.wait_for_timeout(900)
    ok("mouse wheel zooms the map", page.evaluate("MAP.view().zoom") > wheel_before)

    mbox = page.locator("#map").bounding_box()
    popped = False
    for fy in (0.5, 0.45, 0.55, 0.4, 0.6):
        for fx in (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65):
            page.mouse.click(mbox["x"] + mbox["width"] * fx, mbox["y"] + mbox["height"] * fy)
            page.wait_for_timeout(150)
            if page.locator(".fire-popup").count():
                popped = True
                break
        if popped:
            break
    pop_text = page.inner_text(".fire-pop") if popped else ""
    ok("click a fire square: popup explains it", popped and "hotspots" in pop_text, pop_text[:60].replace("\n", " "))
    if popped:
        page.keyboard.press("Escape")

    page.goto(BASE + "/?lang=es")
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=30000)
    wait_idle(page)
    nav_text = page.inner_text(".site-header nav")
    en_label = page.inner_text("#kf-total-label")
    ok("English only: no language switch, ?lang=es is ignored",
       "Español" not in nav_text and page.evaluate("document.documentElement.lang") == "en"
       and "focos" not in en_label.lower(),
       f"nav: {nav_text[:60]!r} / label: {en_label}")

    phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    pp = phone.new_page()
    pp.goto(BASE + "/")
    pp.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=30000)
    pp.wait_for_timeout(800)
    sw = pp.evaluate("document.documentElement.scrollWidth")
    ok("phone: no sideways page scroll", sw <= 390, f"scrollWidth {sw}")
    pp.locator("#results").scroll_into_view_if_needed()
    pp.screenshot(path=SHOTS / "07_phone.png", full_page=False)
    browser.close()

real_errors = [e for e in errors if "400" not in e]   # 400 = the deliberate outside-area test
ok("no browser console errors", not real_errors, "; ".join(real_errors)[:200])
fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
sys.exit(1 if fails else 0)
