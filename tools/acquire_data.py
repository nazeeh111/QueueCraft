#!/usr/bin/env python3
"""Acquire the exact licensed research archive without replacing prior bytes."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

REVISION = "2e74c05ab8c0f5cc5379ca934c2abef857ef2a62"
URL = f"https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-5min-l2/resolve/{REVISION}/btc.parquet"
SHA256 = "1dde1a3be9f1159aec12d7c5b7fddbc912d2e88d65af093adce0c2802f05452f"
LIMIT = 64 * 1024 * 1024


def acquire(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "btc.parquet"
    # Exclusive creation is deliberate: a rerun cannot silently replace evidence.
    attempt = {"url": URL, "started_utc": datetime.now(timezone.utc).isoformat()}
    try:
        with target.open("xb") as output:
            with urllib.request.urlopen(URL, timeout=30) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > LIMIT:
                    raise ValueError("archive exceeds 64 MiB")
                digest = hashlib.sha256()
                count = 0
                while chunk := response.read(65536):
                    count += len(chunk)
                    if count > LIMIT:
                        raise ValueError("archive exceeds 64 MiB")
                    output.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError("archive hash mismatch; preserve file for inspection")
        attempt.update(status="verified", bytes=count, sha256=SHA256)
    except Exception as error:
        attempt.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        with (directory / "acquisition-attempts.jsonl").open("a") as journal:
            journal.write(json.dumps(attempt, sort_keys=True) + "\n")
    return attempt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    print(json.dumps(acquire(args.directory), indent=2))
