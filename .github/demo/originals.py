"""Reproduce the verified local release packs using the theater's public originals."""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

REPO = "MilliganCo/ryzhiy-theater-demo"
TAG = "viewer-objects-v1"


def download(row, directory):
    digest, size, url = row
    assert re.fullmatch("[a-f0-9]{64}", digest)
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.netloc == "redtheater.ru" and parsed.path.startswith("/wp-content/")
    req = Request(quote(url, safe=":/?%&="), headers={"User-Agent": "Ryzhiy-Theater-Archive/1.0"})
    target = directory / digest
    for attempt in range(3):
        try:
            with urlopen(req, timeout=40) as response, target.open("wb") as file:
                shutil.copyfileobj(response, file, 1024**2)
            with target.open("rb") as file:
                if target.stat().st_size != size or hashlib.file_digest(file, "sha256").hexdigest() != digest:
                    raise ValueError(f"Original differs from local export: {digest}")
            return target
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 + attempt)


def publish(digest, rows):
    assert re.fullmatch("[a-f0-9]{64}", digest)
    with tempfile.TemporaryDirectory() as work:
        directory = Path(work)
        with ThreadPoolExecutor(max_workers=4) as pool:
            originals = list(pool.map(lambda row: download(row, directory), rows))
        target = directory / (digest + ".bin")
        with target.open("wb") as output:
            for source in originals:
                with source.open("rb") as data:
                    shutil.copyfileobj(data, output, 1024**2)
        with target.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != digest:
                raise ValueError(f"Pack differs: {digest}")
        subprocess.run(["gh", "release", "upload", TAG, str(target), "-R", REPO], check=True)
    print("Published " + digest, flush=True)


def main():
    packs = json.loads(Path(__file__).with_name("sources.json").read_bytes())
    available = json.loads(subprocess.check_output(["gh", "release", "view", TAG, "-R", REPO, "--json", "assets"]))
    remote = {asset["name"]: asset for asset in available["assets"]}
    failed = []
    for digest, rows in packs.items():
        existing = remote.get(digest + ".bin")
        if existing:
            if existing["digest"] != "sha256:" + digest:
                raise ValueError("Existing pack has a different hash")
            continue
        try:
            publish(digest, rows)
        except Exception as error:
            print(f"Local upload needed for {digest}: {type(error).__name__}", flush=True)
            failed.append(digest)
    if failed:
        raise SystemExit(f"{len(failed)} packs require the local originals")


if __name__ == "__main__":
    main()
