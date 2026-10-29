"""Download the pinned reference XERs:  uv run python tests/reference/fetch.py"""

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference.sources import FILES  # noqa: E402

DATA = Path(__file__).parent / "data"


def fetch(force: bool = False) -> list[Path]:
    out = []
    for name, (url, sha) in FILES.items():
        dest = DATA / name
        if dest.exists() and not force and hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
            out.append(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as r:
            body = r.read()
        got = hashlib.sha256(body).hexdigest()
        if got != sha:
            raise SystemExit(f"{name}: checksum mismatch ({got}), refusing to use it")
        dest.write_bytes(body)
        out.append(dest)
        print(f"fetched {name}")
    return out


if __name__ == "__main__":
    fetch(force="--force" in sys.argv)
    print(f"{len(FILES)} reference files ready in {DATA}")
