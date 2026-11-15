"""Deploy FireBridge to Azure Container Apps (instead of a paid Hugging Face Space).

Uses the same Dockerfile as the Space. Azure builds the image in the cloud (`az containerapp up
--source .`, which respects .dockerignore), so Docker doesn't need to run on this computer.
At startup the app downloads its 4 data files from APP_DATA_URL (our public Hugging Face dataset,
pinned to today's revision so the numbers can't change under the judges) and refreshes the live
FIRMS feed hourly when the FIRMS_MAP_KEY secret is set.

Before running (once, by a human):
    winget install -e --id Microsoft.AzureCLI      # then open a new terminal
    az login                                        # sign in in the browser; pick the subscription

Then:
    python scripts/deploy_azure.py                  # first deploy and every redeploy
    python scripts/deploy_azure.py --delete         # after judging: remove everything (stops billing)

Size: 1 vCPU / 2 GiB (the app peaks at about 1.2 GB) and one replica always on, so judges never
wait for a cold start and the hourly live refresh keeps running. That uses Azure credit every day;
run --delete when the judging is over.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from deploy_space import DEFAULT_DATA_URL  # noqa: E402  (one place for the dataset URL)

GROUP, APP, ENV = "firebridge-rg", "firebridge", "firebridge-env"
LOCATION = "centralus"
PORT = "7860"
SECRET = "firms-key"


def az(*args: str, capture: bool = False, check: bool = True) -> str:
    exe = shutil.which("az") or shutil.which("az.cmd")
    if not exe:
        sys.exit("Azure CLI not found. Run:  winget install -e --id Microsoft.AzureCLI  then open a "
                 "new terminal and run:  az login")
    r = subprocess.run([exe, *args], cwd=REPO, text=True,
                       stdout=subprocess.PIPE if capture else None)
    if check and r.returncode != 0:
        sys.exit(f"az {' '.join(args[:2])} failed (exit {r.returncode}).")
    return (r.stdout or "").strip()


def pin_dataset(data_url: str) -> str:
    """.../datasets/<owner>/<name>/resolve/main/ -> .../resolve/<current commit>/."""
    try:
        repo = data_url.split("/datasets/", 1)[1].split("/resolve/", 1)[0]
        sha = httpx.get(f"https://huggingface.co/api/datasets/{repo}", timeout=30).json()["sha"]
    except Exception as ex:
        print(f"Couldn't pin the dataset version ({ex}); using {data_url} as given.")
        return data_url
    return f"https://huggingface.co/datasets/{repo}/resolve/{sha}/"


def firms_key() -> str | None:
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        try:
            from dotenv import dotenv_values
            key = dotenv_values(REPO / ".env").get("FIRMS_MAP_KEY")
        except ImportError:
            pass
    return key.strip() if key else None


def deploy(data_url: str, set_key: bool) -> None:
    account = json.loads(az("account", "show", "-o", "json", capture=True, check=False) or "null")
    if not account:
        sys.exit("Not signed in to Azure. Run:  az login")
    print(f"Azure subscription: {account['name']}")
    az("extension", "add", "--name", "containerapp", "--upgrade", "--only-show-errors")
    for ns in ("Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry"):
        az("provider", "register", "--namespace", ns, "--wait")
    az("group", "create", "-n", GROUP, "-l", LOCATION, "-o", "none")
    print(f"APP_DATA_URL = {data_url}")
    print("Building the image in Azure and deploying (first time: about 10 minutes) ...")
    az("containerapp", "up", "--name", APP, "--resource-group", GROUP, "--location", LOCATION,
       "--environment", ENV, "--source", ".", "--ingress", "external", "--target-port", PORT,
       "--env-vars", f"APP_DATA_URL={data_url}")
    if set_key:
        key = firms_key()
        if key:
            az("containerapp", "secret", "set", "-n", APP, "-g", GROUP,
               "--secrets", f"{SECRET}={key}", "-o", "none")
            print("Set secret FIRMS_MAP_KEY (live feed refreshes hourly).")
        else:
            print("No FIRMS_MAP_KEY in .env: deploying without the live feed.")
            set_key = False
    env = [f"APP_DATA_URL={data_url}"] + ([f"FIRMS_MAP_KEY=secretref:{SECRET}"] if set_key else [])
    az("containerapp", "update", "-n", APP, "-g", GROUP, "--cpu", "1.0", "--memory", "2.0Gi",
       "--min-replicas", "1", "--max-replicas", "1", "--set-env-vars", *env, "-o", "none")
    fqdn = az("containerapp", "show", "-n", APP, "-g", GROUP,
              "--query", "properties.configuration.ingress.fqdn", "-o", "tsv", capture=True)
    url = f"https://{fqdn}"
    print(f"\nFireBridge: {url}\nWatch the data download: {url}/api/status\n"
          f"Then:  python scripts/check_site.py {url}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Deploy FireBridge to Azure Container Apps.")
    ap.add_argument("--data-url", default=DEFAULT_DATA_URL,
                    help="APP_DATA_URL: dataset folder URL ending in /resolve/main/")
    ap.add_argument("--no-pin", action="store_true", help="don't pin the dataset revision")
    ap.add_argument("--no-key", action="store_true", help="don't set FIRMS_MAP_KEY")
    ap.add_argument("--delete", action="store_true",
                    help=f"delete resource group {GROUP} (the app, its registry and logs)")
    args = ap.parse_args()
    if args.delete:
        az("group", "delete", "-n", GROUP, "--yes")
        print(f"Deleted {GROUP}.")
        return
    deploy(args.data_url if args.no_pin else pin_dataset(args.data_url), not args.no_key)


if __name__ == "__main__":
    main()
