"""
Make the demo video (docs/demo.mp4, under 30 s, 1920x1080, English subtitles burned in) from the
running site, and write the matching docs/video_subtitles.srt.

How:
- text cards are plain HTML rendered by Playwright; the chart is Track A's continuity_texas.png
- app shots are REAL MOTION: the script drives the live app (draws a box, scrolls, clicks tabs,
  opens a past fire, downloads the CSV) and grabs a sharp screenshot every few tens of
  milliseconds, keeping each frame's real time; a cursor overlay shows where it clicks
- ffmpeg fits every shot to its slot, joins them and burns in the subtitles
Every number comes from results/metrics.json or from the live app. No AI images, no NASA logos.

Needs: pip install playwright (Chromium, or Microsoft Edge on Windows) and ffmpeg/ffprobe.
Run from the repo root, with the app running:
    python scripts/record_demo.py --url http://localhost:8000
    python scripts/record_demo.py --url https://<space>.hf.space --site-url <space>.hf.space
"""

import argparse
import base64
import html
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W, H, FPS = 1920, 1080, 30
LIMIT = 30.0
TARGET = 29.0              # stay a full second under the 30 s rule

CARD_CSS = """
body { margin:0; width:1920px; height:1080px; display:flex; align-items:center; justify-content:center;
       background:#1f2328; color:#f4f2ee; font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.box { max-width:1500px; padding:0 80px; }
h1 { font-size:88px; margin:0 0 28px; letter-spacing:-1px; }
p  { font-size:52px; line-height:1.3; margin:0 0 26px; color:#e9e6e0; }
.big { color:#fb923c; font-weight:700; }
.small { font-size:34px; color:#b9b5ae; }
"""

CURSOR_JS = """
(() => {
  if (document.getElementById('demo-cursor')) return;
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24"><path d="M4 2l15 11-7 1-4 7z" fill="#111" stroke="#fff" stroke-width="1.6"/></svg>';
  Object.assign(c.style, {position: 'fixed', left: '0px', top: '0px', zIndex: 2147483647, pointerEvents: 'none',
                          transform: 'translate(-3px,-2px)', transition: 'none'});
  document.body.appendChild(c);
  document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
})();
"""


# ---------------------------------------------------------------------------------------------
class Recorder:
    """Drives a page and grabs frames with their real timestamps."""

    def __init__(self, page, folder):
        self.page, self.folder = page, folder
        folder.mkdir(parents=True, exist_ok=True)
        self.frames, self.mouse = [], (640, 360)

    def snap(self):
        p = self.folder / f"f{len(self.frames):04d}.jpg"
        self.page.screenshot(path=str(p), type="jpeg", quality=90)
        self.frames.append((p, time.perf_counter()))

    def hold(self, seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.snap()

    def move(self, x, y, steps=10):
        x0, y0 = self.mouse
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)                       # ease in-out
            self.page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t)
            self.snap()
        self.mouse = (x, y)

    def click(self, selector, steps=10):
        box = self.page.locator(selector).first.bounding_box()
        self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps)
        self.page.mouse.down(); self.snap(); self.page.mouse.up()
        self.snap()

    def drag(self, x0, y0, x1, y1, steps=14):
        self.move(x0, y0, 8)
        self.page.mouse.down()
        for i in range(1, steps + 1):
            self.page.mouse.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            self.snap()
        self.page.mouse.up()
        self.mouse = (x1, y1)
        self.snap()

    def scroll(self, dy, steps=12):
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(15)
            self.snap()

    def until_loaded(self, max_s=8):
        end = time.perf_counter() + max_s
        while time.perf_counter() < end:
            self.snap()
            if self.page.evaluate("document.getElementById('loading').hidden"):
                break


# ---------------------------------------------------------------------------------------------
def card(page, path, body):
    page.set_content(f"<html><head><style>{CARD_CSS}</style></head><body><div class='box'>{body}</div></body></html>")
    page.screenshot(path=str(path))


def figure_card(page, path, img):
    uri = "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode()   # file:// may not load
    page.set_content(f"""<html><body style="margin:0;width:1920px;height:1080px;background:#fff;display:flex;
      align-items:center;justify-content:center"><img src="{uri}" style="max-width:1840px;max-height:1040px"></body></html>""")
    page.wait_for_timeout(300)
    page.screenshot(path=str(path))


def wait_app(page):
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=60000)
    page.wait_for_function("document.getElementById('loading').hidden", timeout=60000)
    page.wait_for_timeout(1500)


def capture(url, site_url, work):
    from playwright.sync_api import sync_playwright
    metrics = json.loads((REPO / "results" / "metrics.json").read_text())
    ho = metrics["overall"]["holdout"]
    test = metrics["test_years"]
    preset = json.loads((REPO / "docs" / "presets.json").read_text(encoding="utf-8"))[0]
    shots = []                                   # (kind, path or frames, seconds, subtitle)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        cards = browser.new_context(viewport={"width": W, "height": H}).new_page()
        app_ctx = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, accept_downloads=True)
        page = app_ctx.new_page()
        page.goto(url.rstrip("/") + "/")
        wait_app(page)
        k = page.evaluate("""() => ({total: document.getElementById('kf-total').textContent,
                                     pct: document.getElementById('kf-pct').textContent,
                                     year: document.getElementById('kf-year').textContent})""")

        # ---- cards (stills) ----
        c1 = work / "c1.png"
        card(cards, c1, f"<p class='small'>{html.escape(preset['name'].split(',')[0])}, April – July 2011</p>"
                        f"<h1><span class='big'>{html.escape(k['pct'])}</span> its normal fire activity</h1>"
                        f"<p>{html.escape(k['total'])} hotspots"
                        + (f"; {html.escape(k['year'])} is the busiest year on record for this area.</p>" if k["year"] == "2011" else ".</p>"))
        shots.append(("still", c1, 3.0, f"Texas, 2011: {k['pct']} normal fire activity."))
        c2 = work / "c2.png"
        card(cards, c2, "<h1>That record is about to split</h1>"
                        "<p>NASA plans to end MODIS data collection in 2027.</p>"
                        f"<p>Its successor, VIIRS, reports <span class='big'>{ho['raw_viirs']['bias_pct']:+.0f}%</span> "
                        "more hotspots for the same fires.</p>")
        shots.append(("still", c2, 3.0, "MODIS is ending. VIIRS counts don't match."))
        c3 = work / "c3.png"
        figure_card(cards, c3, REPO / "results" / "figures" / "continuity_texas.png")
        shots.append(("still", c3, 3.5, "Raw VIIRS jumps in 2012. Ours doesn't."))
        c4 = work / "c4.png"
        card(cards, c4, f"<p>On years it never saw ({test[0]}–{test[1]}):</p>"
                        f"<h1><span class='big'>{ho['harmonized']['rmse']:,.0f}</span> vs {ho['global_ratio']['rmse']:,.0f}</h1>"
                        "<p>typical monthly error, FireBridge vs one global ratio</p>")
        shots.append(("still", c4, 2.5, "Beats the simple fix on unseen years."))

        # ---- app: real motion ----
        page.evaluate(CURSOR_JS)
        page.mouse.move(640, 360)
        # 1. draw a box: the analyses fill in
        r = Recorder(page, work / "m1")
        r.hold(0.3)
        r.click(".leaflet-draw-draw-rectangle", steps=12)
        m = page.locator("#map").bounding_box()
        cx, cy = m["x"] + m["width"] * 0.42, m["y"] + m["height"] * 0.45
        r.drag(cx - 55, cy - 50, cx + 45, cy + 40)
        r.until_loaded()
        r.hold(0.8)
        shots.append(("frames", r.frames, 3.5, "Draw any area: 25 years of fire."))

        # 2. burning calendar, then "vs normal"
        r = Recorder(page, work / "m2")
        r.move(860, 420, 6)
        r.scroll(page.evaluate("document.querySelector('.tabs').getBoundingClientRect().top - 12"), steps=12)
        r.hold(0.4)
        r.click("input[name=calview][value=anomaly] + span", steps=10)
        r.hold(0.9)
        shots.append(("frames", r.frames, 3.0, "A burning calendar, every month since 2001."))

        # 3. now vs history
        r = Recorder(page, work / "m3")
        r.click("#tab-now", steps=10)
        r.hold(1.2)
        shots.append(("frames", r.frames, 3.0, "This month versus the historical median."))

        # 4. fires vs past: a past fire on the map (a second page, preloaded)
        fires = app_ctx.new_page()
        fires.goto(url.rstrip("/") + "/#area=bbox%3A-106%2C35%2C-105%2C37&label=Northern+New+Mexico&start=2022-04-01"
                   "&end=2022-06-30&base=2003-2022&mode=harmonized&tab=fires&cal=counts&gran=month&metric=count")
        wait_app(fires)
        fires.wait_for_function("document.querySelectorAll('#fires-largest tbody tr').length > 0", timeout=30000)
        fires.evaluate(CURSOR_JS)
        fires.evaluate("document.querySelector('.tabs').scrollIntoView({block: 'start'}); window.scrollBy(0, -12)")
        fires.mouse.move(900, 300)
        r = Recorder(fires, work / "m4")
        r.mouse = (900, 300)
        r.hold(0.6)
        r.scroll(fires.evaluate("document.getElementById('fires-largest').getBoundingClientRect().top - 250"), steps=10)
        r.click('#fires-largest [data-fire="g0"]', steps=10)
        r.until_loaded()
        r.hold(0.8)
        shots.append(("frames", r.frames, 3.5, "The current fire, ranked against every past fire."))

        # 5. download the hotspots CSV (real file, real row count)
        r = Recorder(page, work / "m5")
        page.evaluate("document.getElementById('dl-hotspots').scrollIntoView({block: 'center'})")
        r.mouse = (640, 360)
        with page.expect_download(timeout=120000) as d:
            r.click("#dl-hotspots", steps=10)
        rows = len([l for l in Path(d.value.path()).read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]) - 1
        page.evaluate("""(n) => { const t = document.createElement('div'); t.textContent = n;
            Object.assign(t.style, {position: 'fixed', left: '50%', top: '70px', transform: 'translateX(-50%)',
              background: '#1f2328', color: '#fff', padding: '14px 20px', borderRadius: '10px', zIndex: 5000,
              font: '600 19px Inter, Segoe UI, sans-serif', boxShadow: '0 6px 24px rgba(0,0,0,.35)'});
            document.body.appendChild(t); }""", f"Downloaded {d.value.suggested_filename}: {rows:,} hotspots")
        r.hold(1.0)
        shots.append(("frames", r.frames, 2.0, "Download every hotspot as CSV."))

        c9 = work / "c9.png"
        card(cards, c9, f"<h1>FireBridge</h1><p class='big'>{html.escape(site_url)}</p>"
                        "<p>Built on NASA FIRMS MODIS + VIIRS data</p>"
                        "<p class='small'>NASA Space Apps 2026 · code, methods and checks on GitHub</p>")
        shots.append(("still", c9, 2.0, "FireBridge. Built on NASA FIRMS data."))
        browser.close()
    return shots


# ---------------------------------------------------------------------------------------------
def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Command failed: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r.stdout


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build(shots, out_mp4, work):
    total = sum(s[2] for s in shots)
    assert total <= TARGET, f"storyboard is {total} s (target {TARGET} s)"
    clips, t = [], 0.0
    srt = []
    for i, (kind, src, secs, sub) in enumerate(shots):
        clip = work / f"clip{i}.mp4"
        frames = int(round(secs * FPS))
        if kind == "still":
            vf = (f"scale={W * 2}:{H * 2},zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src), "-vf", vf,
                 "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(clip)])
        else:
            # frames with their real timestamps -> concat list with durations, then fit to the slot
            lst = work / f"frames{i}.txt"
            lines = []
            for j, (p, ts) in enumerate(src):
                nxt = src[j + 1][1] if j + 1 < len(src) else ts + 0.08
                lines.append(f"file '{p.as_posix()}'\nduration {max(0.01, nxt - ts):.4f}")
            lines.append(f"file '{src[-1][0].as_posix()}'")
            lst.write_text("\n".join(lines) + "\n")
            real = src[-1][1] - src[0][1] + 0.08
            speed = secs / real
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                 "-vf", f"setpts=PTS*{speed:.5f},scale={W}:{H},fps={FPS},format=yuv420p",
                 "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(clip)])
        clips.append(clip)
        srt.append(f"{len(srt) + 1}\n{srt_time(t)} --> {srt_time(t + secs)}\n{sub}\n")
        t += secs
    (work / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], cwd=work)
    (REPO / "docs" / "video_subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    shutil.copy(REPO / "docs" / "video_subtitles.srt", work / "subs.srt")
    style = ("FontName=Arial,FontSize=15,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,"
             "BorderStyle=3,Outline=4,Shadow=0,MarginV=14")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", "joined.mp4", "-vf",
         f"subtitles=subs.srt:force_style='{style}'", "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "out.mp4"], cwd=work)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / "out.mp4", out_mp4)


def check(out_mp4):
    info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height:format=duration", "-of", "json", str(out_mp4)]))
    dur = float(info["format"]["duration"])
    w, h = info["streams"][0]["width"], info["streams"][0]["height"]
    print(f"{out_mp4}: {dur:.2f} s, {w}x{h}, {out_mp4.stat().st_size / 1e6:.1f} MB")
    if dur > LIMIT or (w, h) != (W, H):
        sys.exit(f"Video must be <= {LIMIT} s and {W}x{H}.")


def main():
    ap = argparse.ArgumentParser(description="Make docs/demo.mp4 from the running site.")
    ap.add_argument("--url", default="http://localhost:8000", help="where the app is running")
    ap.add_argument("--site-url", default="github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS",
                    help="address shown on the end card (use the live site once deployed)")
    ap.add_argument("--out", default=str(REPO / "docs" / "demo.mp4"))
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shots = capture(args.url, args.site_url, work)
        build(shots, Path(args.out), work)
    check(Path(args.out))


if __name__ == "__main__":
    main()
