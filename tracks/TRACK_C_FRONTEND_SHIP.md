# Track C: Frontend + Ship

**You own:** the website, getting it online, the 30-second video, the README and the
submission itself. Best for whoever will present.
**Your laptop needs:** nothing at first. You build on sample responses until Track B's server
is ready. You also need a free Hugging Face account (huggingface.co) for hosting, and ffmpeg
for the video.
**You hand off to:** the judges.

## How to use this file
1. `git clone https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS` then `cd NASA-SPACEAPPS-VIIRS`
2. Run `claude`, press **Shift+Tab** for plan mode.
3. Paste **C1**. Approve the plan. When it's done and the **check** passes, type `/clear` and
   paste the next prompt. Each prompt says **when** to run it.
4. Post in the team chat at every 📣 handoff.

---

## C1: Website on sample data · start now · target 6:00 pm
```
I'm Track C (Frontend + Ship) of a 3-person team. Read CLAUDE.md, docs/challenge.md,
docs/CONTRACTS.md and tracks/TRACK_C_FRONTEND_SHIP.md first. I only edit the files Track C owns
(docs/CONTRACTS.md §1). The backend isn't ready, so I build against sample data.

1. Create app/static/mock/*.json from the example responses in docs/CONTRACTS.md §4, made
   realistic and bigger: a full month×year grid 2001→2026 for a Texas box with a seasonal cycle
   and 2011 as an extreme year, 12 monthly medians, ranked years, a daily calendar for one month,
   and a timeseries where viirs_raw jumps 3x after 2012 but harmonized doesn't.
2. Build app/static/index.html, methods.html, js/ and css/ per CLAUDE.md §6: plain HTML/JS,
   Leaflet + Leaflet.draw, D3 and Chart.js from a CDN, no build step. One api.js module: with
   ?mock=1 in the URL it loads the mock JSON, otherwise it calls the real /api endpoints.
   Layout: map and area tools (draw, lat/lon box, point + radius, presets) on the left; key
   figures strip, plain-language summary and three tabs (Burning calendar, Patterns & critical
   periods, Now vs history) on the right; raw-vs-harmonized long-term chart with the mode toggle
   below. Exports: hotspots CSV, analytics CSV, PNG of every chart.
   Accessible: viridis/cividis for counts, a colorblind-safe diverging ramp for anomalies,
   legends with units, grey = missing, hatched = provisional, keyboard navigation, ARIA labels,
   works on a phone. Use the frontend-design skill if available. Make it look polished.
3. Serve it with a simple local static server and check every tab, toggle and export with ?mock=1.
   Screenshot each view into docs/screenshots/.
Show the plan and wait for my OK. Then build, commit, `git pull --rebase origin main`, push.
Finish by telling me the next prompt from my track file.
```
**Check:** open it yourself with `?mock=1`, click everything, and try it on your phone.

---

## C2: Get a test site online today · after C1 · target 7:00 pm
```
Set up hosting now so Sunday has no surprises. Target Hugging Face Spaces (Docker type, free
CPU). Write a Dockerfile (python:3.11-slim, installs requirements.txt, copies app/, downloads
data/app/ at startup from env var APP_DATA_URL if set, runs uvicorn app.main:app on port 7860)
and a .dockerignore. If Track B's app/main.py isn't pushed yet, make the container serve
app/static with ?mock=1 working. Give me click-by-click steps to create the Space, add secrets
(FIRMS_MAP_KEY, APP_DATA_URL) and push to it. Commit, pull --rebase, push.
```
**Check:** a public `*.hf.space` URL loads the site in an incognito window on your phone.
📣 **Handoff:** post the test URL in the team chat.

---

## C3: Connect to the real API · when Track B posts "API runs" (~6 pm) and again at "API on real data" (~9:30 pm)
```
Track B's API is running at <URL, e.g. http://127.0.0.1:8000>. Make the real API the default
(?mock=1 still works). Test the full flow with Playwright: draw an area, lat/lon box,
point+radius, presets, date range, baseline years, all three tabs, the mode toggle, both CSV
exports, PNG exports, and the Methods page. Fix UI bugs myself. List any API mismatches with the
endpoint, what we sent, and what came back, so I can pass them to Track B. Then go through
docs/challenge.md R1–R18 and tell me where each is visible in the app. Commit, pull --rebase,
push.
```

## C4: Presets + Methods page · when Track A posts presets and methods text (~10 pm)
```
Track A wrote docs/presets.json and docs/methods_text.md. Wire the presets into the preset
buttons, and build methods.html from methods_text.md plus results/metrics.json (shown as a clear
before/after table: raw VIIRS vs global ratio vs our method) and the figures in results/figures/.
Only numbers from metrics.json. Check it on a phone screen size. Commit, pull --rebase, push.
```

---

## C5: Deploy for real · Sunday by 2:00 pm (with Track B)
```
Deploy the full app to our Hugging Face Space with the real data. Upload data/app/ somewhere
the Space can download it (a Hugging Face dataset repo is easiest; give me the steps), set
APP_DATA_URL and FIRMS_MAP_KEY as Space secrets, and redeploy. Then run the Playwright flow from
C3 against the live URL and report any failures. Put the live URL at the top of README.md.
Commit, pull --rebase, push.
```
**Check:** the live URL works in incognito on a phone, including the CSV downloads.

---

## C6: Video, README, submission text · Sunday 2:00–6:00 pm
```
Our demo is a VIDEO: 30 seconds max with English subtitles (check the 2026 Submission Guide;
going over makes us ineligible for Global Judging). Use only numbers from results/metrics.json
and the live app.
1. docs/video_script.md: a storyboard that fits in 27 seconds. 0–4 s: the problem (MODIS ending,
   VIIRS doesn't match, the 2012 jump). 4–9 s: the raw vs harmonized long-term chart, the jump
   disappears. 9–12 s: our method vs the simple global-ratio fix (one number). 12–24 s: the live
   app: draw an area, the burning calendar appears, current month vs median, download the
   hotspots CSV. 24–27 s: name, URL, "Built on NASA FIRMS MODIS + VIIRS data". For each shot:
   start/end, what's on screen, a subtitle of at most 8 words.
2. docs/video_subtitles.srt matching the script.
3. scripts/record_demo.py: Playwright records the app shots at 1920×1080 on the live URL;
   title and chart shots are rendered from results/figures/ and plain text cards; ffmpeg joins
   them, burns in the subtitles, writes docs/demo.mp4. Check with ffprobe that it's ≤ 30.0 s and
   1080p and tell me the exact duration. No AI-generated images, no NASA logos.
4. README.md: what it is, live link, video link (placeholder), the problem, NASA data used and
   how it shaped the project (with DOIs), method, validation results table, how to run locally,
   limitations, AI-use disclosure, team.
5. docs/AI_USE.md: exactly where and how we used Claude Code.
6. docs/submission_text.md: text for each Space Apps form field (title, summary, how it meets
   the challenge, NASA data used, AI use), plus steps to upload demo.mp4 to YouTube as Unlisted
   with subtitles.
Commit (skip demo.mp4 if over 50 MB), pull --rebase, push.
```
**Check:** watch the video with the sound off. Every subtitle readable, 30 s or less.
If the auto-recorded video looks robotic, record the app on your screen yourself
(Windows: Win+G, Xbox Game Bar), and ask Claude to cut it to 27 s and burn in the subtitles.

---

## C7: Fresh-eyes judge review · Sunday ~8:00 pm (whole team)
Paste **KICKOFF_PROMPTS.md Prompt 8** with the live URL. Fix what you own; send API issues to
Track B and science issues to Track A.

## C8: Submit · Sunday by 10:00 pm (deadline 11:59 pm)
On the Space Apps site, open your team's project page and fill it in from
`docs/submission_text.md`: project link (live URL), video link (YouTube Unlisted), repo link
(https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS). Check every link in incognito, then
click **Submit**.
