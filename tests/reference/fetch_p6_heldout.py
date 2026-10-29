"""Fetch the P6-scheduled held-out corpus:  uv run python tests/reference/fetch_p6_heldout.py

danafitkowski/cpp-cpm-engine (MIT) publishes 30 sets of 12 synthetic P6 schedules, each
frozen from a public randomness-beacon round before P6 saw it, imported into P6
Professional 23.12.1, scheduled with F9 and read back from P6's own database
(validation/held-out/PROTOCOL.md there). Pinned by commit: git checks the content.

Only validation/held-out is checked out (sparse, blob-filtered), into
tests/reference/data/p6-heldout/. Needs git.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference.sources import P6_HELDOUT_COMMIT, P6_HELDOUT_REPO  # noqa: E402

DATA = Path(__file__).parent / "data" / "p6-heldout"
HELD_OUT = DATA / "validation" / "held-out"


def fetch(force: bool = False) -> Path:
    stamp = DATA / ".commit"
    if HELD_OUT.is_dir() and stamp.exists() and stamp.read_text().strip() == P6_HELDOUT_COMMIT and not force:
        return HELD_OUT

    def git(*args):
        subprocess.run(["git", "-C", str(DATA), *args], check=True, capture_output=True, text=True)

    DATA.mkdir(parents=True, exist_ok=True)
    if not (DATA / ".git").exists():
        git("init", "-q")
        git("remote", "add", "origin", P6_HELDOUT_REPO)
    git("sparse-checkout", "set", "validation/held-out")
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", P6_HELDOUT_COMMIT)
    git("checkout", "-q", "--force", "FETCH_HEAD")
    head = subprocess.run(["git", "-C", str(DATA), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    if head.stdout.strip() != P6_HELDOUT_COMMIT:
        raise SystemExit(f"checked out {head.stdout.strip()}, expected {P6_HELDOUT_COMMIT}")
    stamp.write_text(P6_HELDOUT_COMMIT)
    return HELD_OUT


if __name__ == "__main__":
    out = fetch(force="--force" in sys.argv)
    sets = sorted(p.name for p in out.iterdir() if p.is_dir() and p.name.startswith("H"))
    print(f"{len(sets)} sets ready in {out}")
