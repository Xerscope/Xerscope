"""Third-party XER files whose correct results are stated by their authors.

Pinned by commit and SHA-256 so the expected values in expected.py can never drift
from the files they describe. Not vendored: MPXJ is LGPL and xerlock is AGPL, so the
files are downloaded into tests/reference/data/ (git-ignored) by fetch.py. P6-Viewer is MIT.
"""

MPXJ_COMMIT = "8c4f6462e66dab196e92e32bcf4196586d33d740"  # joniles/mpxj
XERLOCK_COMMIT = "dc27e4bc311233df1761162da243c4143901bb40"  # joaompfp/xerlock
P6VIEWER_COMMIT = "c32dc4c46502adf8d8338ed1abac119aedf21f75"  # CodeVision3000/P6-Viewer (MIT)

_MPXJ = f"https://raw.githubusercontent.com/joniles/mpxj/{MPXJ_COMMIT}/junit/data"
_XERLOCK = f"https://raw.githubusercontent.com/joaompfp/xerlock/{XERLOCK_COMMIT}"
_P6VIEWER = f"https://raw.githubusercontent.com/CodeVision3000/P6-Viewer/{P6VIEWER_COMMIT}/XER%20Files"

# local name -> (url, sha256)
FILES: dict[str, tuple[str, str]] = {
    # Real P6 exports (P6 8.2 / 8.4 / 20.12) used by MPXJ's own unit tests.
    "mpxj/PredecessorCalendar.xer": (
        f"{_MPXJ}/PredecessorCalendar.xer",
        "46f3c1c68552429cf32191ebc8f48d12f52e517481b6fb588ad1955937c5cd1d",
    ),
    "mpxj/SuccessorCalendar.xer": (
        f"{_MPXJ}/SuccessorCalendar.xer",
        "ab420cc573be248ef7ef344f77b204176c3263fceb45c27866276929bf1e59e2",
    ),
    "mpxj/TwentyFourHourCalendar.xer": (
        f"{_MPXJ}/TwentyFourHourCalendar.xer",
        "9b91bf5bfcc0df4f6a2fec8867a923af7758058c224a9772a728e8d2ba0f0fc5",
    ),
    "mpxj/ProjectDefaultCalendar.xer": (
        f"{_MPXJ}/ProjectDefaultCalendar.xer",
        "e48eb3a53b7e8f40a5a87af8e983e9932c298baeb572e3a901b3961f997674ef",
    ),
    "mpxj/percent-complete-8.4.xer": (
        f"{_MPXJ}/generated/task-percentcomplete/percent-complete-8.4.xer",
        "71e56568075852d00507ff5506d5c055912ce0ba0982b97b8ace6269f794d10a",
    ),
    "mpxj/resource-rates-test.xer": (
        f"{_MPXJ}/assignment/resource-rates-test.xer",
        "7298574bb32ac3068b07b427a35cd2834308d2fcb0e2ac74fea4e013e738c62e",
    ),
    # 24-activity schedule whose every stored date xerlock's CPM engine reproduces,
    # plus xerlock's parse of it (its test_fixture.py asserts the JSON equals its parser).
    "xerlock/sample-schedule.xer": (
        f"{_XERLOCK}/examples/sample-schedule.xer",
        "53d7ba3ca743110d65d853cfd18900cba697b47bf6107da5d53438dbe995991b",
    ),
    # Real P6 exports, scheduled by P6 (all early/late dates and floats stored): the ground
    # truth for analysis/cpm.py. Hotel: P6 6.0, 4,217 activities, 7,586 links (FS/SS/FF/SF),
    # 11 calendars with holidays, ALAP, must-finish-by. Terminal: P6 5.0, 66 activities, SNLT.
    "p6viewer/Hotel Project.xer": (
        f"{_P6VIEWER}/Hotel%20Project.xer",
        "d2c413088afed805b30b7628c91be8aca870f7d4daf00eb12a547d69913d8352",
    ),
    "p6viewer/TERMINAL BUILDING-AIRPORT.xer": (
        f"{_P6VIEWER}/TERMINAL%20BUILDING-AIRPORT.xer",
        "a2f3b2469e26f19985ac801786c90edfb965a7bc194a6e57704aa845c5f8611f",
    ),
    "xerlock/sample-schedule.json": (
        f"{_XERLOCK}/frontend/src/utils/fixtures/sample-schedule.json",
        "db7336f3d10641cd70091d7e3dd69467c3f05abed462368acccc39394bafc0d6",
    ),
}
