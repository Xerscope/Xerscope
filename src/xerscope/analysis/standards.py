"""Standards as data.

A standard is a TOML file: a header plus a list of metrics, each one a rule from
``rules.py`` with its parameters and a target. The built-in ones (P6 Check Schedule,
DCMA 14-Point) live in ``xerscope/standards/``; yours can live anywhere and use the same
format (see ``custom-template.toml``)::

    [standard]
    id = "ACME"
    name = "ACME scheduling standard"

    [[metric]]
    id = "ACME-01"
    name = "Open ends"
    rule = "missing_logic"
    target = "<= 2%"
    params = { exclude = ["complete", "loe"], succ_exempt = ["project_finish"] }

A file is validated on load (unknown rule, parameter or value -> error naming it), so a
typo fails loudly instead of silently changing a result.
"""

from __future__ import annotations

import operator
import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .rules import RULES, Unit

_OPS = {"<=": operator.le, ">=": operator.ge, "==": operator.eq, "<": operator.lt, ">": operator.gt}
_TARGET = re.compile(r"^\s*(<=|>=|==|<|>)\s*(-?\d+(?:\.\d+)?)\s*(%?)\s*$")
UNITS = {"%", "ratio", "count", "days", "pass/fail"}


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    standard: str
    rule: str
    description: str = ""
    params: dict = field(default_factory=dict, hash=False, compare=False)
    unit: Unit = "%"
    comparator: str | None = None  # None = informational
    threshold: float | None = None
    source: str = ""
    group: str = ""  # section of the report (P6: Inflexibility and Inefficiency, ...)

    @property
    def needs_baseline(self) -> bool:
        return RULES[self.rule].needs_baseline

    @property
    def threshold_label(self) -> str:
        if self.unit == "pass/fail" and self.comparator:
            return "pass"
        if self.comparator is None or self.threshold is None:
            return "info"
        return f"{self.comparator} {self.threshold:g}{'%' if self.unit == '%' else ''}"

    def evaluate(self, value: float | None) -> str:
        if value is None:
            return "n/a"
        if self.comparator is None or self.threshold is None:
            return "info"
        return "pass" if _OPS[self.comparator](round(value, 6), self.threshold) else "fail"


@dataclass(frozen=True)
class Standard:
    id: str
    name: str
    metrics: tuple[Metric, ...]
    description: str = ""
    source: str = ""
    path: str = ""

    def __getitem__(self, metric_id: str) -> Metric:
        return next(m for m in self.metrics if m.id == metric_id)


def parse_target(text: str | None, unit: str) -> tuple[str | None, float | None]:
    if text is None or str(text).strip().lower() in ("", "info"):
        return None, None
    if str(text).strip().lower() == "pass":
        return "==", 1.0
    m = _TARGET.match(str(text))
    if not m:
        raise ValueError(f"target {text!r}: write e.g. '<= 5%', '>= 0.95', '== 0' or 'pass'")
    if m.group(3) and unit != "%":
        raise ValueError(f"target {text!r} is a percentage but the metric unit is {unit!r}")
    return m.group(1), float(m.group(2))


def parse_standard(data: dict, path: str = "") -> Standard:
    where = path or "standard"
    head = data.get("standard")
    if not isinstance(head, dict) or "id" not in head or "name" not in head:
        raise ValueError(f"{where}: needs a [standard] table with id and name")
    metrics = []
    seen = set()
    for i, m in enumerate(data.get("metric", [])):
        label = f"{where}: metric #{i + 1} ({m.get('id', '?')})"
        try:
            for key in ("id", "name", "rule"):
                if key not in m:
                    raise ValueError(f"missing {key!r}")
            if m["id"] in seen:
                raise ValueError("duplicate id")
            seen.add(m["id"])
            if m["rule"] not in RULES:
                raise ValueError(f"unknown rule {m['rule']!r}; available: {sorted(RULES)}")
            rule = RULES[m["rule"]]
            params = dict(m.get("params", {}))
            rule.validate(params)
            unit = m.get("unit", rule.unit)
            if unit not in UNITS:
                raise ValueError(f"unit {unit!r} not in {sorted(UNITS)}")
            comparator, threshold = parse_target(m.get("target"), unit)
            extra = set(m) - {"id", "name", "rule", "description", "params", "unit", "target", "source", "group"}
            if extra:
                raise ValueError(f"unknown key(s) {sorted(extra)}")
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
        metrics.append(
            Metric(
                id=m["id"],
                name=m["name"],
                standard=head["name"],
                rule=m["rule"],
                description=m.get("description", rule.doc.splitlines()[0] if rule.doc else ""),
                params=params,
                unit=unit,
                comparator=comparator,
                threshold=threshold,
                source=m.get("source", ""),
                group=m.get("group", ""),
            )
        )
    if not metrics:
        raise ValueError(f"{where}: no [[metric]] defined")
    return Standard(head["id"], head["name"], tuple(metrics), head.get("description", ""), head.get("source", ""), path)


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), or UTF-16 as Windows PowerShell 5 writes with '>'."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def load_standard(path: str | Path) -> Standard:
    p = Path(path)
    return loads_standard(decode(p.read_bytes()), p.name)


def loads_standard(text: str | bytes, name: str = "uploaded.toml") -> Standard:
    if isinstance(text, bytes):
        text = decode(text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{name}: invalid TOML: {exc}") from None
    return parse_standard(data, name)


BUILTIN_DIR = resources.files("xerscope") / "standards"


def builtin_standards() -> dict[str, Standard]:
    out = {}
    for entry in sorted(BUILTIN_DIR.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml") and not entry.name.startswith("custom-template"):
            s = parse_standard(tomllib.loads(entry.read_text(encoding="utf-8")), entry.name)
            out[s.id] = s
    return out


def template_text() -> str:
    return (BUILTIN_DIR / "custom-template.toml").read_text(encoding="utf-8")


def discover_standards(*dirs: str | Path) -> tuple[dict[str, Standard], list[str]]:
    """Built-ins plus every ``*.toml`` in ``dirs``; returns (standards, load errors)."""
    found = builtin_standards()
    errors = []
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.toml")):
            try:
                s = load_standard(p)
                if s.id in found:
                    errors.append(f"{p.name}: id {s.id!r} replaces the standard of that id ({found[s.id].name})")
                found[s.id] = s
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
    return found, errors
