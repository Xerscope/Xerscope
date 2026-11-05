"""Acronyms shown on the pages: full name, definition, source.

One table feeds the help of every column and card whose label holds an acronym, and the
Glossary expander under each page. A label's acronym missing here fails tests/test_glossary.py.
"""

import re

# acronym -> (full name, definition, source)
GLOSSARY: dict[str, tuple[str, str, str]] = {
    "AC": (
        "Actual Cost (ACWP)",
        "Labor units actually spent to date, on every task.",
        "DoD EVM terms (Actual Cost of Work Performed); P6 Actual Labor Units",
    ),
    "ACWP": ("Actual Cost of Work Performed", "DoD name of AC.", "DoD EVM terms"),
    "BAC": (
        "Budget at Completion",
        "Total budgeted labor units of the baseline.",
        "DoD EVM terms",
    ),
    "BCWP": ("Budgeted Cost of Work Performed", "DoD name of EV.", "DoD EVM terms"),
    "BCWS": ("Budgeted Cost of Work Scheduled", "DoD name of PV.", "DoD EVM terms"),
    "BEI": (
        "Baseline Execution Index",
        "Tasks completed / tasks due by the status date (baseline finish on or before it); "
        "below 0.95 is flagged. P6's variant divides by every baseline task.",
        "DCMA-EA PAM 200.1 §3.1.2.4; P6 Check Schedule (BEI)",
    ),
    "BL": ("Baseline", "The reference schedule the update is measured against.", "P6 (BL columns)"),
    "CPI": (
        "Cost Performance Index",
        "EV / AC; below 1 means the work earned cost more than budgeted.",
        "DoD EVM terms",
    ),
    "CPL": (
        "Critical Path Length",
        "Working days from the status date to the forecast finish of the project.",
        "DCMA-EA PAM 200.1 §3.1.2.3",
    ),
    "CPLI": (
        "Critical Path Length Index",
        "(CPL + total float of the finish) / CPL; below 0.95 is flagged.",
        "DCMA-EA PAM 200.1 §3.1.2.3",
    ),
    "CSV": ("Comma-Separated Values", "Plain text table, one row per line.", "RFC 4180"),
    "DCMA": (
        "Defense Contract Management Agency",
        "US DoD agency; its 14-Point Assessment and DECM are schedule quality checks.",
        "DCMA-EA PAM 200.1",
    ),
    "DECM": (
        "DCMA EVMS Compliance Metrics",
        "DCMA's current schedule metrics, identified by code (06A204b...).",
        "DCMA DECM v8.0",
    ),
    "EAC": ("Estimate at Completion", "AC + ETC: labor units the work will have taken when done.", "DoD EVM terms"),
    "ETC": ("Estimate to Complete", "Remaining labor units.", "DoD EVM terms"),
    "EV": (
        "Earned Value (BCWP)",
        "Baseline budget × Performance % complete: the budget of the work done.",
        "DoD EVM terms; P6 Earned Value Labor Units",
    ),
    "EVM": ("Earned Value Management", "Measuring progress as budget earned against budget planned.", "ANSI/EIA-748"),
    "FF": ("Finish to Finish", "Relationship: the successor finishes after the predecessor finishes.", "P6"),
    "FS": ("Finish to Start", "Relationship: the successor starts after the predecessor finishes.", "P6"),
    "ID": ("Identifier", "Code of a task (P6 Activity ID), stable from one export to the next.", "P6"),
    "LOE": (
        "Level of Effort",
        "Task whose dates follow its relationships and that drives nothing (supervision...).",
        "P6 (Level of Effort activity type)",
    ),
    "MTA": (
        "Milestone Trend Analysis",
        "Forecast of each milestone at each update, plotted against the status date.",
        "xerscope",
    ),
    "PAM": ("Program Analysis Pamphlet", "DCMA-EA PAM 200.1, home of the 14-Point Assessment.", "DCMA"),
    "PPC": (
        "Percent Plan Complete",
        "Finishes and starts forecast at W−1 before W's status date that happened / those "
        "commitments; milestones left out.",
        "Last Planner (LCI) counts finishes only; xerscope adds starts. Commitments read from the W−1 forecast",
    ),
    "PV": (
        "Planned Value (BCWS)",
        "Baseline budget × Schedule % complete: the budget of the work planned to date.",
        "DoD EVM terms; P6 Planned Value Labor Units",
    ),
    "SF": ("Start to Finish", "Relationship: the successor finishes after the predecessor starts.", "P6"),
    "SPI": (
        "Schedule Performance Index",
        "EV / PV; below 1 means less work done than planned.",
        "DoD EVM terms; P6 Schedule Performance Index",
    ),
    "SS": ("Start to Start", "Relationship: the successor starts after the predecessor starts.", "P6"),
    "SV": ("Schedule Variance", "EV − PV; negative means behind plan.", "DoD EVM terms"),
    "TF": ("Total Float", "How long a task can slip without moving the project finish.", "P6"),
    "VAC": ("Variance at Completion", "BAC − EAC; negative means an overrun.", "DoD EVM terms"),
    "WBS": ("Work Breakdown Structure", "The tree the tasks are filed under.", "P6"),
    "XER": ("Primavera XER", "P6's tab-separated export file.", "Oracle"),
    "wd": ("working days", "Working days of the task's calendar (project calendar for project totals).", "DCMA"),
}

_TOKEN = re.compile(r"\b(?:[A-Z]{2,}|wd)\b")


def acronyms(text: str) -> list[str]:
    """The glossary's acronyms in ``text``, in order of appearance, each once."""
    return list(dict.fromkeys(token for token in _TOKEN.findall(text) if token in GLOSSARY))


def unknown_acronyms(text: str) -> list[str]:
    """Upper-case tokens of ``text`` the glossary lacks."""
    return [token for token in dict.fromkeys(_TOKEN.findall(text)) if token not in GLOSSARY]


def spelled_out(text: str) -> str:
    """One line per acronym of ``text``: "SPI: Schedule Performance Index. EV / PV; ..." ("" if none)."""
    lines = [f"{token}: {GLOSSARY[token][0]}. {GLOSSARY[token][1]}" for token in acronyms(text)]
    return "\n\n".join(lines)
