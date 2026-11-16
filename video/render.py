"""
Render video/reel.html into the demo video.

    python video/render.py --stills 1.5,6,12.5      # a few frames as PNGs into video/out/ (to check)
    python video/render.py                          # every frame -> video/out/reel_silent.mp4
    python video/soundtrack.py                      # -> video/out/soundtrack.wav
    python video/render.py --mux                    # silent video + soundtrack -> docs/demo_reel.mp4

Also writes docs/demo_reel_subtitles.srt from the reel's captions and on-screen text.
Needs: playwright (Chromium or Edge) and ffmpeg on PATH.
"""

import argparse
import functools
import http.server
import shutil
import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "out"
FPS = 30
W, H = 1920, 1080


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def open_page(p, port):
    try:
        b = p.chromium.launch()
    except Exception:
        b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto(f"http://127.0.0.1:{port}/reel.html?render=1")
    pg.wait_for_function("window.READY === true", timeout=120000)
    return b, pg


def srt_time(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(pg):
    items = pg.evaluate("[...window.SCREEN_TEXT, ...window.CAPTIONS].sort((a, b) => a[0] - b[0])")
    lines = []
    for i, (a, b, text) in enumerate(items, 1):
        text = text.replace("<hl>", "").replace("</hl>", "")
        lines += [str(i), f"{srt_time(a)} --> {srt_time(b)}", text, ""]
    path = REPO / "docs" / "demo_reel_subtitles.srt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", help="comma-separated times in seconds")
    ap.add_argument("--mux", action="store_true", help="join out/reel_silent.mp4 + out/soundtrack.wav")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    ff = shutil.which("ffmpeg") or "ffmpeg"

    if a.mux:
        dst = REPO / "docs" / "demo_reel.mp4"
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(OUT / "reel_silent.mp4"), "-i", str(OUT / "soundtrack.wav"),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dst)],
                       check=True)
        print("wrote", dst)
        return

    srv = serve()
    with sync_playwright() as p:
        b, pg = open_page(p, srv.server_address[1])
        if a.stills:
            for s in a.stills.split(","):
                pg.evaluate(f"render({float(s)})")
                pg.screenshot(path=str(OUT / f"still_{float(s):05.2f}.png"))
                print("still", s)
            b.close()
            return
        dur = pg.evaluate("window.DURATION")
        n = int(round(dur * FPS))
        enc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
                                "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                                "-movflags", "+faststart", str(OUT / "reel_silent.mp4")], stdin=subprocess.PIPE)
        for i in range(n):
            pg.evaluate(f"render({i / FPS})")
            enc.stdin.write(pg.screenshot(type="png"))
            if i % 60 == 0:
                print(f"frame {i}/{n}", flush=True)
        enc.stdin.close()
        enc.wait()
        write_srt(pg)
        b.close()
    print("wrote", OUT / "reel_silent.mp4", f"({n} frames, {n / FPS:.2f} s)")


if __name__ == "__main__":
    main()
