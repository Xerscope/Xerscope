"""xerscope's P6 Check Schedule against P6 Professional 24 reports on real schedules.

Each witness is a local folder under tests/reference/data/witness/ (ignored by git, like
every .xer and .csv; CI has none and skips) holding:

- one anonymised ``.xer`` (the app's "XER extract" download of the export the report ran on)
- ``baseline.xer``: the baseline the report used, anonymised too (optional; none if absent)
- ``expected.csv``: the report's summary typed as ``id,found,total``, one line per check

The anonymised file is checked, not the original: a match proves the anonymisation kept every
count as well. Run before merging any change to the checks or the CPM:
``XERSCOPE_REQUIRE=witness uv run pytest tests/test_p6_witness.py``.
"""

from pathlib import Path

import pytest
from conftest import missing

from xerscope import cli

WITNESS = Path(__file__).parent / "reference" / "data" / "witness"
HINT = f"no witness folder under {WITNESS} (anonymised .xer + expected.csv)"


def _witnesses() -> list[Path]:
    if not WITNESS.is_dir():
        return []
    return sorted(d for d in WITNESS.iterdir() if (d / "expected.csv").is_file())


@pytest.mark.parametrize("folder", _witnesses() or [None], ids=lambda d: d.name if d else "none")
def test_p6_check_schedule_reproduces_the_witness_report(capsys, folder):
    if folder is None:
        missing("witness", HINT)
    schedules = [p for p in folder.glob("*.xer") if p.name != "baseline.xer"]
    assert len(schedules) == 1, f"{folder.name}: one schedule .xer expected besides baseline.xer"
    args = ["check", str(schedules[0]), "--standard", "P6", "--expect", str(folder / "expected.csv")]
    if (folder / "baseline.xer").is_file():
        args += ["--baseline", str(folder / "baseline.xer")]
    code = cli.main(args)
    out = capsys.readouterr()
    assert code == 0, out.err.strip()
    assert "all counts match" in out.out
