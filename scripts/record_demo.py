"""
Make the 27-second demo video (docs/demo.mp4) from the running site. Storyboard:
docs/video_script.md. Subtitles: docs/video_subtitles.srt (burned in).

How: Playwright renders the text cards from plain HTML and takes 1920x1080 screenshots of the
app; ffmpeg turns each still into a clip with a slow zoom, joins them, burns in the subtitles.
No AI-generated images, no NASA logos. Every number comes from results/metrics.json or from
the live app (the CSV row count is read from the real download).

Needs: pip install playwright (Chromium, or Microsoft Edge on Windows) and ffmpeg/ffprobe.
Run from the repo root, with the app running:
    python scripts/record_demo.py --url http://localhost:8000
    python scripts/record_demo.py --url https://<space>.hf.space --site-url <space>.hf.space
"""

import argparse
import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FPS = 30
W, H = 1920, 1080
# (seconds, kind) in storyboard order; must add up to <= 30 s (we use 27 s)
SHOTS = [(4, "card_problem"), (5, "figure"), (3, "card_result"), (3, "app_area"),
         (3, "app_calendar"), (3, "app_now"), (3, "app_csv"), (3, "card_end")]

CARD_CSS = """
body { margin:0; width:1920px; height:1080px; display:flex; align-items:center; justify-content:center;
       background:#1f2328; color:#f4f2ee; font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.box { max-width:1500px; padding:0 80px; }
h1 { font-size:88px; margin:0 0 28px; letter-spacing:-1px; }
p  { font-size:52px; line-height:1.3; margin:0 0 26px; color:#e9e6e0; }
.big { color:#fb923c; font-weight:700; }
.small { font-size:34px; color:#b9b5ae; }
"""


def card(page, path, body):
    page.set_content(f"<html><head><style>{CARD_CSS}</style></head><body><div class='box'>{body}"
                     "</div></body></html>")
    page.screenshot(path=str(path))


def figure_card(page, path, img):
    import base64
    # embedded as data: a page set with set_content may not load file:// images
    uri = "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode()
    page.set_content(f"""<html><body style="margin:0;width:1920px;height:1080px;background:#fff;
      display:flex;align-items:center;justify-content:center">
      <img src="{uri}" style="max-width:1840px;max-height:1040px"></body></html>""")
    page.wait_for_timeout(300)
    page.screenshot(path=str(path))


def wait_loaded(page):
    page.wait_for_function("document.getElementById('kf-total').textContent !== '–'", timeout=60000)
    page.wait_for_function("document.getElementById('loading').hidden", timeout=60000)
    page.wait_for_timeout(1200)


def capture(url, site_url, out_dir):
    from playwright.sync_api import sync_playwright
    m = json.loads((REPO / "results" / "metrics.json").read_text())["overall"]["holdout"]
    raw_bias = m["raw_viirs"]["bias_pct"]
    ours, ratio = m["harmonized"]["rmse"], m["global_ratio"]["rmse"]
    test = json.loads((REPO / "results" / "metrics.json").read_text())["test_years"]
    paths = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="msedge")
        cards = browser.new_context(viewport={"width": W, "height": H})
        page = cards.new_page()

        paths["card_problem"] = out_dir / "01.png"
        card(page, paths["card_problem"],
             "<h1>25 years of fire records are about to split</h1>"
             "<p>NASA plans to end MODIS data collection in 2027.</p>"
             f"<p>Its successor, VIIRS, reports <span class='big'>{raw_bias:+.0f}%</span> more "
             "hotspots for the same fires.</p>")
        paths["figure"] = out_dir / "02.png"
        figure_card(page, paths["figure"], REPO / "results" / "figures" / "continuity_texas.png")
        paths["card_result"] = out_dir / "03.png"
        card(page, paths["card_result"],
             f"<p>On years it never saw ({test[0]}–{test[1]}):</p>"
             f"<h1><span class='big'>{ours:,.0f}</span> vs {ratio:,.0f}</h1>"
             "<p>typical monthly error, FireBridge vs one global ratio</p>"
             "<p class='small'>hotspots per month, all three regions (results/metrics.json)</p>")

        # ---- the app: a 1280x720 layout drawn at 1.5x = 1920x1080, so the UI is readable ----
        app = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5,
                                  accept_downloads=True)
        page = app.new_page()
        page.goto(url.rstrip("/") + "/")
        wait_loaded(page)
        paths["app_area"] = out_dir / "04.png"
        page.screenshot(path=str(paths["app_area"]))

        page.evaluate("document.querySelector('.tabs').scrollIntoView({block: 'start'}); window.scrollBy(0, -12)")
        page.wait_for_timeout(500)
        paths["app_calendar"] = out_dir / "05.png"
        page.screenshot(path=str(paths["app_calendar"]))

        page.click("#tab-now")
        page.wait_for_timeout(900)
        page.evaluate("document.querySelector('.tabs').scrollIntoView({block: 'start'}); window.scrollBy(0, -12)")
        paths["app_now"] = out_dir / "06.png"
        page.screenshot(path=str(paths["app_now"]))

        # real download; then show the button and the file that came back
        page.click("#tab-calendar")
        page.evaluate("document.getElementById('dl-hotspots').scrollIntoView({block: 'center'})")
        with page.expect_download(timeout=120000) as d:
            page.click("#dl-hotspots")
        dl = d.value
        lines = [l for l in Path(dl.path()).read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#")]
        rows = len(lines) - 1
        note = (f"Downloaded {html.escape(dl.suggested_filename)}: {rows:,} hotspots with "
                "location, time, satellite, fire power and confidence")
        page.evaluate("""(note) => {
            const b = document.getElementById('dl-hotspots');
            b.style.outline = '4px solid #c2410c'; b.style.outlineOffset = '3px';
            const t = document.createElement('div');
            t.textContent = note;
            Object.assign(t.style, {position: 'fixed', left: '50%', top: '70px', transform: 'translateX(-50%)',
              background: '#1f2328', color: '#fff', padding: '14px 20px', borderRadius: '10px',
              boxShadow: '0 6px 24px rgba(0,0,0,.35)', font: '600 19px Inter, Segoe UI, sans-serif',
              zIndex: 5000, width: '900px', textAlign: 'center'});
            document.body.appendChild(t);
        }""", note)
        page.wait_for_timeout(400)
        paths["app_csv"] = out_dir / "07.png"
        page.screenshot(path=str(paths["app_csv"]))

        page = cards.new_page()
        paths["card_end"] = out_dir / "08.png"
        card(page, paths["card_end"],
             "<h1>FireBridge</h1>"
             f"<p class='big'>{html.escape(site_url)}</p>"
             "<p>Built on NASA FIRMS MODIS + VIIRS data</p>"
             "<p class='small'>NASA Space Apps 2026 · code and methods on GitHub</p>")
        browser.close()
    return paths


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Command failed: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r.stdout


def build_video(paths, out_mp4, work):
    clips = []
    for i, (secs, kind) in enumerate(SHOTS):
        clip = work / f"clip{i}.mp4"
        frames = secs * FPS
        # slow push-in: zoom 1.00 -> 1.04 over the shot (upscale first so it stays smooth)
        vf = (f"scale={W * 2}:{H * 2},zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(paths[kind]),
             "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", str(clip)])
        clips.append(clip)
    (work / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", "joined.mp4"], cwd=work)
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
    if dur > 30.0 or (w, h) != (W, H):
        sys.exit("Video must be <= 30.0 s and 1920x1080.")


def main():
    ap = argparse.ArgumentParser(description="Make docs/demo.mp4 from the running site.")
    ap.add_argument("--url", default="http://localhost:8000", help="where the app is running")
    ap.add_argument("--site-url", default="github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS",
                    help="address shown on the end card (use the live site once deployed)")
    ap.add_argument("--out", default=str(REPO / "docs" / "demo.mp4"))
    args = ap.parse_args()
    assert sum(s for s, _ in SHOTS) <= 30
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        paths = capture(args.url, args.site_url, work)
        build_video(paths, Path(args.out), work)
    check(Path(args.out))


if __name__ == "__main__":
    main()
