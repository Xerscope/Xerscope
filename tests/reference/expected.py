"""Results stated by the authors of the reference files (see sources.py).

Every value cites where it is stated. Nothing here was produced by xerscope.
"""

# --- MPXJ src/test/java/org/mpxj/junit/XerRelationshipLagCalendarTest.java ----------
# Each file is the same P6 project exported with a different "calendar for relationship
# lag" scheduling option (SCHEDOPTIONS.sched_calendar_on_relationship_lag).
LAG_CALENDAR = {
    "mpxj/PredecessorCalendar.xer": "rcal_Predecessor",
    "mpxj/SuccessorCalendar.xer": "rcal_Successor",
    "mpxj/TwentyFourHourCalendar.xer": "rcal_24Hour",
    "mpxj/ProjectDefaultCalendar.xer": "rcal_ProjDefault",
}

# --- MPXJ src/test/java/org/mpxj/junit/task/TaskPercentCompleteTest.java --------------
# P6 8.4 export; activity name -> % complete P6 shows for that activity's % type.
PERCENT_COMPLETE_FILE = "mpxj/percent-complete-8.4.xer"
PERCENT_COMPLETE = {
    "Duration 0%": 0,
    "Duration 25%": 25,
    "Duration 75%": 75,
    "Duration 100%": 100,
    "Physical 0%": 0,
    "Physical 25%": 25,
    "Physical 75%": 75,
    "Physical 100%": 100,
    "Units 0%": 0,
    "Units 25%": 25,
    "Units 75%": 75,
    "Units 100%": 100,
}

# --- xerlock tests/test_standards.py::test_percent_complete_follows_the_activity_type --
_BASE = {"status_code": "TK_Active", "target_drtn_hr_cnt": "80", "remain_drtn_hr_cnt": "20", "phys_complete_pct": "10"}
PERCENT_RULES = [  # (row, expected %)
    ({**_BASE, "complete_pct_type": "CP_Phys"}, 10),
    ({**_BASE, "complete_pct_type": "CP_Drtn"}, 75),
    ({**_BASE, "complete_pct_type": "CP_Units", "act_work_qty": "30", "remain_work_qty": "90"}, 25),
    ({**_BASE, "complete_pct_type": "CP_Units"}, 10),  # no units -> physical figure
    ({**_BASE, "complete_pct_type": "CP_Drtn", "status_code": "TK_Complete"}, 100),
    ({**_BASE, "complete_pct_type": "CP_Drtn", "remain_drtn_hr_cnt": "100"}, 0),  # never negative
]

# --- xerlock sample (DEMO-DC-01) ---------------------------------------------------------
XERLOCK_FILE = "xerlock/sample-schedule.xer"
XERLOCK_JSON = "xerlock/sample-schedule.json"
# Stated in the fixture's "project" block and in docs/screenshots/health-check.png.
XERLOCK_PROJECT = {
    "activities": 24,
    "critical": 9,
    "longest_path": 10,
    "milestones": 3,
    "complete": 3,
    "in_progress": 3,
    "not_started": 18,
    "pct_activities_complete": 12.5,
    "data_date": "2026-03-02 08:00",
    "finish": "2026-09-08 16:00",
    "lag_calendar": "rcal_Predecessor",
}

# DCMA results for the analysis step. Sources: docs/screenshots/health-check.png
# (each count re-derived from the pinned file and found consistent), tests/test_standards.py
# (CPLI hand calculation) and tests/test_cpm_sample.py (critical path test).
# Population: incomplete activities; baseline = planned (target_*) dates in the file.
DCMA = {
    "DCMA-01": {
        "numerator": 2,
        "note": "xerlock counts SS/SF-only 'dangling' finishes "
        "(MEP-060, FIT-010) and exempts the project finish "
        "milestone; a plain no-successor count gives 1 (MS-030)",
    },
    "DCMA-02": {"numerator": 0},
    "DCMA-03": {"numerator": 4},
    "DCMA-04": {"numerator": 25, "denominator": 27},  # 25 FS + 2 SS into incomplete work
    "DCMA-05": {"numerator": 2},  # CX-040, MS-030: CS_MEOB (finish on or before)
    "DCMA-06": {"numerator": 5},
    "DCMA-07": {"numerator": 0},
    "DCMA-08": {"numerator": 2},  # MEP-010, MEP-020
    "DCMA-09": {"numerator": 0},
    "DCMA-11": {"numerator": 4},
    "DCMA-12": {"status": "pass"},  # +600 wd on MEP-020 moves MS-030 2026-09-08 -> 2028-12-27
    # xerlock states 1.0 (CPL 1080 h = 135 wd x 8 h, TF 0). The file has no Must Finish By
    # date, so that float is 0 by construction and the index says nothing: n/a here
    # (docs/formulas.md, DCMA-13).
    "DCMA-13": {"status": "n/a"},
}
