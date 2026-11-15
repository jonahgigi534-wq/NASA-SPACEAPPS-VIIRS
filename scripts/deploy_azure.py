"""Deploy FireBridge to Azure Container Apps (instead of a paid Hugging Face Space).

Uses the same Dockerfile and file list as the Space. Azure builds the image in the cloud
(`az containerapp up --source <folder with just those files>`), so Docker doesn't need to run here.
At startup the app downloads its 4 data files from APP_DATA_URL (our public Hugging Face dataset,
pinned to today's revision so the numbers can't change under the judges) and refreshes the live
FIRMS feed hourly when the FIRMS_MAP_KEY secret is set.

Before running (once, by a human):
    winget install -e --id Microsoft.AzureCLI      # then open a new terminal
    az login                                        # sign in in the browser; pick the subscription

Then:
    python scripts/deploy_azure.py                  # first deploy and every redeploy
    python scripts/deploy_azure.py --local-build    # Azure for Students: cloud builds are blocked,
                                                    # so build with local Docker and push instead
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
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from deploy_space import DEFAULT_DATA_URL, UPLOAD  # noqa: E402  (same URL + file list as the Space)

GROUP, APP, ENV = "firebridge-rg", "firebridge", "firebridge-env"
# Azure for Students only allows a few regions (northcentralus, francecentral, norwayeast,
# denmarkeast, belgiumcentral); North Central US (Chicago) is the closest to our regions' users.
LOCATION = "northcentralus"
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


def build_context(dest: Path) -> int:
    """Copy only the files the app needs (the Space's UPLOAD list) into dest. `az containerapp up`
    packs the whole --source folder, data/ included (gigabytes), so it gets this folder instead."""
    n = 0
    for pattern in UPLOAD:
        for f in REPO.glob(pattern):
            if f.is_file():
                out = dest / f.relative_to(REPO)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                n += 1
    return n


def registry() -> tuple[str, str]:
    """(name, login server) of the container registry in our group; created if missing."""
    found = az("acr", "list", "-g", GROUP, "--query", "[0].[name, loginServer]", "-o", "tsv",
               capture=True).split()
    if found:
        return found[0], found[1]
    name = f"firebridge{os.urandom(3).hex()}"
    az("acr", "create", "-n", name, "-g", GROUP, "--sku", "Basic", "-o", "none")
    return name, az("acr", "show", "-n", name, "--query", "loginServer", "-o", "tsv", capture=True)


def push_local_image() -> tuple[str, str]:
    """Build with the local Docker and push to our registry. For subscriptions that block Azure's
    cloud builds (Azure for Students: TasksOperationsNotAllowed)."""
    docker = shutil.which("docker") or sys.exit("--local-build needs Docker running on this computer")
    name, server = registry()
    # admin user: lets the container app pull the image; az stores the credential itself
    az("acr", "update", "-n", name, "--admin-enabled", "true", "-o", "none")
    az("acr", "login", "-n", name)
    image = f"{server}/firebridge:{time.strftime('%Y%m%d-%H%M%S')}"
    if os.environ.get("FIREBRIDGE_IMAGE"):           # reuse an image pushed by an earlier run
        return os.environ["FIREBRIDGE_IMAGE"], name, server
    print(f"Building and pushing {image} ...")
    for cmd in (["build", "-t", image, "."], ["push", image]):
        if subprocess.run([docker, *cmd], cwd=REPO).returncode != 0:
            sys.exit(f"docker {cmd[0]} failed")
    return image, name, server


def deploy_image(image: str, name: str, server: str, data_url: str) -> None:
    """Create the app from a pushed image, or point the existing app at it. The registry's admin
    credential goes straight from one az call to the next (never printed); managed identity isn't
    available on the 'express' environments Azure for Students gets."""
    exists = az("containerapp", "list", "-g", GROUP, "--query", f"[?name=='{APP}'] | length(@)",
                "-o", "tsv", capture=True) == "1"
    user = az("acr", "credential", "show", "-n", name, "--query", "username", "-o", "tsv", capture=True)
    pwd = az("acr", "credential", "show", "-n", name, "--query", "passwords[0].value", "-o", "tsv",
             capture=True)
    if exists:
        az("containerapp", "registry", "set", "-n", APP, "-g", GROUP, "--server", server,
           "--username", user, "--password", pwd, "-o", "none")
        az("containerapp", "update", "-n", APP, "-g", GROUP, "--image", image, "-o", "none")
        return
    az("containerapp", "create", "-n", APP, "-g", GROUP, "--environment", ENV, "--image", image,
       "--registry-server", server, "--registry-username", user, "--registry-password", pwd,
       "--ingress", "external", "--target-port", PORT, "--env-vars", f"APP_DATA_URL={data_url}",
       "-o", "none")


def deploy(data_url: str, set_key: bool, location: str, local_build: bool) -> None:
    account = json.loads(az("account", "show", "-o", "json", capture=True, check=False) or "null")
    if not account:
        sys.exit("Not signed in to Azure. Run:  az login")
    print(f"Azure subscription: {account['name']}")
    az("extension", "add", "--name", "containerapp", "--upgrade", "--only-show-errors")
    for ns in ("Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry"):
        az("provider", "register", "--namespace", ns, "--wait")
    az("group", "create", "-n", GROUP, "-l", location, "-o", "none")
    print(f"APP_DATA_URL = {data_url}")
    if local_build:
        image, name, server = push_local_image()
        deploy_image(image, name, server, data_url)
    else:
        print("Building the image in Azure and deploying (first time: about 10 minutes) ...")
        with tempfile.TemporaryDirectory(prefix="firebridge-build-") as ctx:
            print(f"Build context: {build_context(Path(ctx))} files")
            az("containerapp", "up", "--name", APP, "--resource-group", GROUP, "--location",
               location, "--environment", ENV, "--ingress", "external", "--target-port", PORT,
               "--env-vars", f"APP_DATA_URL={data_url}", "--source", ctx)
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
    ap.add_argument("--location", default=LOCATION, help="Azure region (default: %(default)s)")
    ap.add_argument("--local-build", action="store_true",
                    help="build with local Docker and push (when Azure blocks cloud builds)")
    ap.add_argument("--no-key", action="store_true", help="don't set FIRMS_MAP_KEY")
    ap.add_argument("--delete", action="store_true",
                    help=f"delete resource group {GROUP} (the app, its registry and logs)")
    args = ap.parse_args()
    if args.delete:
        az("group", "delete", "-n", GROUP, "--yes")
        print(f"Deleted {GROUP}.")
        return
    deploy(args.data_url if args.no_pin else pin_dataset(args.data_url), not args.no_key,
           args.location, args.local_build)


if __name__ == "__main__":
    main()
