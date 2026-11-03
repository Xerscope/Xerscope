"""Schedule analysis: rules, standards (TOML profiles) and the analyses built on them."""

from . import dcma, decm, integrity, p6  # noqa: F401 - registers the one-function-per-check rules
from .baseline import Baseline
from .checks import (
    AnalysisContext,
    CheckResult,
    compare_counts,
    health_history,
    results_frame,
    run_metric,
    run_standard,
)
from .rules import RULES, Rule, RuleOutput
from .standards import (
    Metric,
    Standard,
    builtin_standards,
    discover_standards,
    load_standard,
    loads_standard,
    template_text,
)

__all__ = [
    "RULES",
    "AnalysisContext",
    "Baseline",
    "CheckResult",
    "Metric",
    "Rule",
    "RuleOutput",
    "Standard",
    "builtin_standards",
    "compare_counts",
    "discover_standards",
    "health_history",
    "load_standard",
    "loads_standard",
    "results_frame",
    "run_metric",
    "run_standard",
    "template_text",
]
