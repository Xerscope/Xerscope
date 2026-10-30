"""Build MPXJ's CPM scheduler from a pinned commit:  uv run python tests/reference/mpxj_cpm.py

The MPXJ release on PyPI (16.10.0) predates the fix of joniles/mpxj#972 (out-of-sequence
progress, checked by its reporter against real P6 schedules). The ``org.mpxj.cpm``
package of the pinned commit is compiled against the released jar and put first on the
classpath (``XERSCOPE_MPXJ_CPM_JAR``, set by tests/conftest.py when the jar exists).
Nothing of MPXJ (LGPL) is vendored: the sources are fetched from GitHub at that commit.
Needs git and a JDK (javac).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MPXJ_CPM_COMMIT = "8c4f6462e66dab196e92e32bcf4196586d33d740"  # joniles/mpxj master, 2026-10-28
REPO = "https://github.com/joniles/mpxj"
JAVA_RELEASE = "21"  # oldest Java the crosscheck job runs: the jar then loads on every LTS it tests
JAR = Path(__file__).parent / "data" / f"mpxj-cpm-{MPXJ_CPM_COMMIT[:7]}.jar"


def _mpxj_lib() -> Path:
    import mpxj

    return Path(mpxj.__file__).parent / "lib"


def build(force: bool = False) -> Path:
    if JAR.exists() and not force:
        return JAR
    for tool in ("git", "javac"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed to build MPXJ's scheduler")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mpxj"

        def git(*args):
            subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True)

        src.mkdir()
        git("init", "-q")
        git("remote", "add", "origin", REPO)
        git("sparse-checkout", "set", "src/main/java/org/mpxj/cpm")
        git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", MPXJ_CPM_COMMIT)
        git("checkout", "-q", "FETCH_HEAD")
        files = sorted((src / "src/main/java/org/mpxj/cpm").glob("*.java"))
        if not files:
            raise SystemExit("no org.mpxj.cpm sources at the pinned commit")
        classes = Path(tmp) / "classes"
        sep = ";" if sys.platform == "win32" else ":"
        cp = sep.join(str(j) for j in sorted(_mpxj_lib().glob("*.jar")))
        javac = ["javac", "--release", JAVA_RELEASE, "-nowarn", "-d", str(classes), "-cp", cp]
        subprocess.run([*javac, *map(str, files)], check=True)
        JAR.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(JAR, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(classes.rglob("*.class")):
                z.write(f, f.relative_to(classes).as_posix())
    return JAR


if __name__ == "__main__":
    print(f"built {build(force='--force' in sys.argv)}")
