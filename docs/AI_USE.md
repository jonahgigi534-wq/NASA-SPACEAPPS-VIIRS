# How we used AI

**Tool:** Claude Code (Anthropic), used as a coding assistant by all three members of the team,
each working on one part of the project (data and science, backend, website and delivery).

## Where we used it

| Part | What Claude Code did | What the team did |
|---|---|---|
| Planning | Helped turn the challenge text into a spec (`CLAUDE.md`), a requirements checklist (`docs/challenge.md`) and the contracts between the three parts (`docs/CONTRACTS.md`) | Chose the approach, regions and priorities; reviewed and edited the plan |
| Data pipeline and harmonization (`pipeline/`) | Wrote code to ingest the FIRMS archives, grid them, fit and compare the harmonization methods, and compute the validation metrics and figures | Downloaded the NASA data, ran the pipeline, checked counts, figures and results, decided which method to use |
| Backend (`app/main.py`, `app/analytics.py`, `pipeline/live.py`) | Wrote the API, the analytics (climatology, anomalies, fire season, current month vs median), the live FIRMS feed, and the tests | Set the requirements, reviewed results against direct database queries (`pipeline/science_check.py`), supplied the FIRMS key |
| Website (`app/static/`) | Wrote the HTML, CSS and JavaScript, and a browser test that clicks through every feature | Directed the design, checked it on desktop and phone |
| Debugging | Found and fixed bugs (for example a crash when a period had no satellite data, and a change in the FIRMS API's request limit) | Reported problems, confirmed fixes |
| Writing | Drafted the README, the methods text, the video storyboard and the submission text | Reviewed and edited everything; the final wording is the team's responsibility |
| Video (`scripts/record_demo.py`) | Wrote the script that captures screenshots of the site and assembles the video with ffmpeg | Reviewed the video |
| Motion reel (`video/`, `docs/demo_reel.mp4`) | Wrote the code that captures the live site (`capture.py`), animates it with the yearly chart and titles (`reel.html`), synthesizes the music from sine waves and noise (`soundtrack.py`) and renders it (`render.py`) | Reviewed the reel |

## What AI did not do

- **No numbers were made up.** Every number in the app, on the methods page, in the README and
  in the video comes from the pipeline's output on NASA data (`results/metrics.json`) or from the
  live app. A separate check (`pipeline/science_check.py`) compares the app's numbers with direct
  queries of the data.
- **No AI-generated images or video.** The charts are drawn from the data; the video is made of
  screenshots of the real site, the pipeline's own figures and plain text cards. The motion reel's
  app shots are screenshots of the live site, its chart uses the live API's yearly totals, and its
  animation and music are drawn and synthesized by our own code; no generative image, video, music
  or voice model was used.
- No NASA logos or mission branding are used.
