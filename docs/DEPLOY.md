# Deploying FireBridge to Hugging Face Spaces

The site runs as a **Docker Space** on Hugging Face's free CPU tier. The data is not in the
image: when the container starts, the app downloads the 4 data files from our public dataset
<https://huggingface.co/datasets/JonathanGigi/SPACEAPPS-DATA> and, if a FIRMS key is set,
refreshes the live FIRMS feed in the background once an hour.

## One command (recommended)

1. Get a Hugging Face **write** token: huggingface.co → your avatar → **Settings** →
   **Access Tokens** → **Create new token** → type **Write** → copy it.
2. In the repo folder:
   ```
   pip install huggingface_hub
   hf auth login
   ```
   Paste the token when asked (it is stored by Hugging Face's tool, not in the repo).
3. Deploy (replace `yourname`):
   ```
   python scripts/deploy_space.py --space yourname/firebridge
   ```
   This creates the Space (public, Docker), uploads only the files the app needs, and sets
   `APP_DATA_URL` (variable) and `FIRMS_MAP_KEY` (secret, read from `.env`).
   `APP_DATA_URL` is pinned to the dataset's current commit, so the live numbers can't change
   if someone updates the dataset later (`--no-pin` to follow the latest version instead).
   **Recommended:** add `--with-data data/app` to bundle the 4 data files (about 530 MB) into the
   image. A free Space sleeps when nobody visits and wakes with an empty disk; with the data
   bundled it answers in seconds instead of re-downloading for about 2 minutes.
4. Wait for the build (a few minutes), then about 2 minutes for the data download. Check:
   - `https://yourname-firebridge.hf.space/api/status`: download finished, live refresh ok
   - `https://yourname-firebridge.hf.space`: the site, in an incognito window and on a phone
5. To update after code changes: run step 3 again.

## By hand (if the script can't be used)

1. huggingface.co → **New** → **Space**. Name `firebridge`, SDK **Docker** (Blank),
   hardware **CPU basic (free)**, visibility **Public** → **Create Space**.
2. Space → **Settings** → **Variables and secrets**:
   - **New variable** `APP_DATA_URL` =
     `https://huggingface.co/datasets/JonathanGigi/SPACEAPPS-DATA/resolve/main/`
     (the folder URL ending in `/resolve/main/`; a URL ending in a file name also works)
   - **New secret** `FIRMS_MAP_KEY` = your FIRMS map key (optional: without it the site works
     but has no hourly live feed)
3. Upload the files listed in `UPLOAD` in `scripts/deploy_space.py` (Space → **Files** →
   **Add file** → **Upload files**, keeping folders), plus a `README.md` that starts with the
   settings block in `SPACE_README` in the same script (`sdk: docker`, `app_port: 7860`).

## Settings the app reads

| Variable | Default | Meaning |
|---|---|---|
| `APP_DATA_URL` | (none) | Dataset folder URL; missing data files are downloaded at startup |
| `APP_DATA_DIR` | `data/app` (Docker: `/home/user/app/data/app`) | Where the data files live |
| `FIRMS_MAP_KEY` | (none) | Turns on the hourly live FIRMS refresh |
| `LIVE_REFRESH` | `1` | `0` turns the live refresh off |
| `LIVE_CACHE_DIR` | `data/cache/live` | FIRMS download cache |

## Running the same container locally

```
docker build -t firebridge .
docker run -p 7860:7860 -e APP_DATA_URL=https://huggingface.co/datasets/JonathanGigi/SPACEAPPS-DATA/resolve/main/ -e FIRMS_MAP_KEY=... firebridge
```
Then open http://localhost:7860.
