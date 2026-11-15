"""
Deploy FireBridge to a Hugging Face Space (Docker, free CPU) in one command.

What it does:
  1. creates the Space if it doesn't exist (public, Docker type)
  2. uploads only what the app needs: Dockerfile, requirements.txt, app/, pipeline/live.py,
     Track A's presets / methods text / metrics.json / figures (never data/, .env or tests)
  3. writes the Space's own README (the settings block Hugging Face needs: sdk docker, port 7860)
  4. sets APP_DATA_URL (a public variable) and FIRMS_MAP_KEY (a secret) on the Space
The Space then builds the Docker image and starts; at startup the app downloads the data from
APP_DATA_URL. Watch progress at https://huggingface.co/spaces/<space>?logs=container and on
<space URL>/api/status.

One-time setup (see docs/DEPLOY.md):
  pip install huggingface_hub
  hf auth login            # paste a token with WRITE access from huggingface.co/settings/tokens

Run from the repo root:
  python scripts/deploy_space.py --space <user>/firebridge
  (FIRMS_MAP_KEY is read from .env or the environment; --no-key to skip it)
"""

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DATA_URL = "https://huggingface.co/datasets/JonathanGigi/SPACEAPPS-DATA/resolve/main/"
GITHUB = "https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS"

# Only these go to the Space (paths relative to the repo root; globs allowed)
UPLOAD = [
    "Dockerfile", ".dockerignore", "requirements.txt",
    "app/__init__.py", "app/main.py", "app/analytics.py", "app/static/**",
    "pipeline/__init__.py", "pipeline/live.py",
    "docs/presets.json", "docs/methods_text.md",
    "results/metrics.json", "results/figures/*.png", "results/extra/*.json", "results/extra/*.png",
]

SPACE_README = f"""---
title: FireBridge
emoji: 🔥
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Harmonized MODIS + VIIRS burning activity calendar
---

# FireBridge

Fire activity from 2001 to today for any area, from NASA FIRMS MODIS and VIIRS hotspots
harmonized onto one consistent scale. NASA Space Apps 2026.

Code, methods and validation: {GITHUB}
"""


def pin_dataset(api, data_url):
    """.../datasets/<owner>/<name>/resolve/main/ -> .../resolve/<today's commit>/, so the numbers
    on the live site can't change under the judges if someone updates the dataset."""
    try:
        repo = data_url.split("/datasets/", 1)[1].split("/resolve/", 1)[0]
        sha = api.dataset_info(repo).sha
    except Exception as ex:
        print(f"Couldn't pin the dataset version ({ex}); using {data_url} as given.")
        return data_url
    return f"https://huggingface.co/datasets/{repo}/resolve/{sha}/"


def main():
    ap = argparse.ArgumentParser(description="Deploy FireBridge to a Hugging Face Space.")
    ap.add_argument("--space", required=True, help="Space id, e.g. yourname/firebridge")
    ap.add_argument("--data-url", default=DEFAULT_DATA_URL,
                    help="APP_DATA_URL: dataset folder URL ending in /resolve/main/")
    ap.add_argument("--no-key", action="store_true", help="don't set FIRMS_MAP_KEY")
    ap.add_argument("--no-pin", action="store_true",
                    help="use the dataset's latest version instead of pinning today's commit")
    ap.add_argument("--with-data", metavar="DIR",
                    help="also upload the 4 data files from DIR into the image (about 530 MB), "
                         "so a sleeping Space wakes without re-downloading them")
    args = ap.parse_args()

    try:
        from huggingface_hub import HfApi
    except ImportError:
        sys.exit("Please run:  pip install huggingface_hub   (then: hf auth login)")
    api = HfApi()
    try:
        who = api.whoami()["name"]
    except Exception:
        sys.exit("Not logged in to Hugging Face. Run:  hf auth login   (token with WRITE access)")
    print(f"Logged in as {who}. Deploying to Space {args.space} ...")

    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True,
                    private=False)
    api.upload_folder(repo_id=args.space, repo_type="space", folder_path=str(REPO),
                      allow_patterns=UPLOAD, commit_message="Deploy FireBridge")
    api.upload_file(repo_id=args.space, repo_type="space", path_in_repo="README.md",
                    path_or_fileobj=SPACE_README.encode("utf-8"),
                    commit_message="Space settings")

    if args.with_data:
        data_dir = Path(args.with_data)
        need = ["cells_daily.parquet", "missing_days.parquet", "hotspots.parquet", "coverage.json"]
        absent = [f for f in need if not (data_dir / f).exists()]
        if absent:
            sys.exit(f"--with-data: {data_dir} is missing {', '.join(absent)}")
        print(f"Uploading the data files from {data_dir} into the image (large files use LFS) ...")
        api.upload_folder(repo_id=args.space, repo_type="space", folder_path=str(data_dir),
                          path_in_repo="appdata", allow_patterns=need,
                          commit_message="Bundle app data")

    data_url = args.data_url if args.no_pin else pin_dataset(api, args.data_url)
    api.add_space_variable(args.space, "APP_DATA_URL", data_url)
    print(f"APP_DATA_URL = {data_url}")
    if not args.no_key:
        key = os.environ.get("FIRMS_MAP_KEY")
        if not key:
            try:
                from dotenv import dotenv_values
                key = dotenv_values(REPO / ".env").get("FIRMS_MAP_KEY")
            except ImportError:
                pass
        if key:
            api.add_space_secret(args.space, "FIRMS_MAP_KEY", key.strip())
            print("Set secret FIRMS_MAP_KEY (live feed refreshes hourly).")
        else:
            print("No FIRMS_MAP_KEY found: the site works, but without the hourly live feed.")

    url = f"https://{args.space.replace('/', '-').lower()}.hf.space"
    print(f"\nDone. The Space is building (a few minutes), then downloads the data (~2 min).")
    print(f"  Build logs: https://huggingface.co/spaces/{args.space}?logs=build")
    print(f"  Status:     {url}/api/status")
    print(f"  Site:       {url}")


if __name__ == "__main__":
    main()
