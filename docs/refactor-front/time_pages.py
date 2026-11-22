"""Time first render vs rerun per page on the demo series; count hot calls per run."""
import os, sys, time, collections
os.environ["XERSCOPE_SYNC_LOAD"] = "1"
os.environ.pop("XERSCOPE_BASELINE", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from pathlib import Path
import xerscope
from xerscope.sample import generate
from streamlit.testing.v1 import AppTest
from conftest import read_folder

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
if not list(out.glob("*.xer")):
    generate(out, weeks=8)
os.environ["XERSCOPE_DATA"] = str(out)

counts = collections.Counter()
def wrap(module, name, label=None):
    original = getattr(module, name)
    def counted(*a, **k):
        counts[label or f"{module.__name__.split('.')[-1]}.{name}"] += 1
        return original(*a, **k)
    setattr(module, name, counted)

import xerscope.app.state as state
import xerscope.analysis.baseline as bl
import xerscope.analysis.standards as stds
import xerscope.xer as xer
for n in ["_parse", "_baseline_options", "_folder_baseline_names", "_baseline_file_source", "_renumbered_counts",
          "_baselines_without_guid", "data_identity", "memo", "standards", "baseline_for", "_apply_file_choices",
          "_chosen_items", "_file_digest", "_digest", "_resolution", "_export_baseline", "_file_baseline",
          "run_metric"]:
    wrap(state, n)
wrap(bl, "relinked"); wrap(bl, "renumbered")
wrap(stds, "discover_standards")
wrap(xer, "pmxml_files"); wrap(xer, "xer_files")
state.Baseline.planned = staticmethod(lambda *a, _o=state.Baseline.planned, **k: (counts.__setitem__("Baseline.planned", counts["Baseline.planned"]+1), _o(*a, **k))[1])
_fs = state.Baseline.from_snapshot
state.Baseline.from_snapshot = classmethod(lambda cls, *a, **k: (counts.__setitem__("Baseline.from_snapshot", counts["Baseline.from_snapshot"]+1), _fs(*a, **k))[1])

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
t0 = time.perf_counter()
at = AppTest.from_file(APP, default_timeout=300).run()
t1 = time.perf_counter()
at = read_folder(at)
t2 = time.perf_counter()
print(f"startup(empty) {t1-t0:.2f}s ; read_folder(8 files)+baseline Done {t2-t1:.2f}s")
baseline_choice = sys.argv[2] if len(sys.argv) > 2 else None
if baseline_choice:
    at.session_state["bl_choice"] = baseline_choice
    at.run()
print("bl_choice =", at.session_state.get("bl_choice"))
pages = ["overview", "gantt", "health", "audit", "changelog", "forensics", "earned_value", "milestones", "ppc", "export", "activity", "debug"]
for page in pages:
    counts.clear()
    t = time.perf_counter(); at.switch_page(f"views/{page}.py").run(); first = time.perf_counter() - t
    counts.clear()
    t = time.perf_counter(); at.run(); rerun = time.perf_counter() - t
    c_rerun = dict(counts); counts.clear()
    t = time.perf_counter(); at.run(); rerun2 = time.perf_counter() - t
    err = [e.value[:80] for e in at.exception]
    print(f"\n{page:13s} first {first:6.2f}s  rerun {rerun:6.2f}s  rerun2 {rerun2:6.2f}s  {err}")
    hot = {k: v for k, v in c_rerun.items() if v}
    print("  rerun calls:", dict(sorted(hot.items(), key=lambda kv: -kv[1])))
