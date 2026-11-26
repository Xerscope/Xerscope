"""The Gantt Ask field's local agent, off unless XERSCOPE_AGENT=on (docs/deploy.md §12).

The keyword grammar answers first (analysis/ask); a sentence it does not fully read goes to the local
model, which chooses one command of ``tools.FIELDS`` and one of its values under a JSON schema built
from the columns of the update's view: for ``query``, the conditions, sort, limit and grouping on
those columns; for an activity, its ID; for ``simulate_delay``, the working days. xerscope runs the
command and writes the sentence from a template: every Activity ID, date and number said is a value
a command computed. A choice outside the lists, an Activity ID the update does not hold, a word the
question does not hold, or a command that cannot be read gives no answer, said as such. ``client`` is
the only module of xerscope that opens a connection, to the local model only.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..analysis import activity_view as views
from ..analysis.ask.text import fold
from . import client, tools


@dataclass(frozen=True)
class AgentAnswer:
    """What the agent said, and how.

    The choice read from the model, the values the command computed, the sentence written from them
    (empty with ``refused``), the Activity IDs the answer is about (``codes``: the Gantt draws them),
    the seconds the model took, which model answered (``model``: "fast" when the cascade's first one
    did, "main" otherwise) and its reasoning, when XERSCOPE_AGENT_THINKING asked for one.
    """

    choice: tools.Choice
    values: dict
    sentence: str
    refused: str
    codes: tuple[str, ...]
    seconds: float
    model: str = "main"
    reasoning: str = ""

    @property
    def command(self) -> str:
        """The command chosen."""
        return self.choice.command

    @property
    def field(self) -> str:
        """The value of the command chosen."""
        return self.choice.field


def schema_for(view: views.View) -> dict:
    """Return the JSON schema of the model's reply, its column names those of ``view``: flat, closed."""
    names = [column.name for column in view.columns]
    words = [column.name for column in view.columns if column.kind == views.TEXT]
    condition = {
        "type": "object",
        "properties": {
            "column": {"type": "string", "enum": names},
            "op": {"type": "string", "enum": list(views.ALL_OPERATORS)},
            "value": {"type": "string"},
        },
        "required": ["column", "op", "value"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string", "enum": list(tools.FIELDS)},
            "field": {"type": "string", "enum": sorted({f for fields in tools.FIELDS.values() for f in fields})},
            "activity_id": {"type": "string"},
            "days": {"type": "number"},
            "conditions": {"type": "array", "items": condition, "maxItems": tools.MAX_CONDITIONS},
            "sort_by": {"type": "string", "enum": ["", *names]},
            "descending": {"type": "boolean"},
            "limit": {"type": "integer"},
            "group_by": {"type": "string", "enum": ["", *words]},
        },
        "required": ["command", "field"],
        "additionalProperties": False,
    }


def system_prompt(view: views.View) -> str:
    """Return the model's instructions: the commands and their values, the columns and their operators."""
    lines = [
        "You turn a question about a construction schedule into ONE command and ONE of its values, as JSON.",
        "Commands [values]:",
        *(f"- {command} [{', '.join(tools.FIELDS[command])}]: {what}" for command, what in tools.COMMANDS.items()),
        "For query, give conditions (all must hold) on these columns, and optionally sort_by, descending, limit,",
        "group_by. Value `count` = how many, `list` = which, `groups` = how many per value of group_by.",
        "Columns (kind: operators):",
    ]
    for column in view.columns:
        values = f" Values: {', '.join(column.values)}." if column.values else ""
        lines.append(
            f"- {column.name} ({column.kind}: {', '.join(views.OPERATORS[column.kind])}): {column.english}.{values}"
        )
    lines += [
        "Dates are YYYY-MM-DD; a month is two conditions (>= its first day, < the next month's first day).",
        "Numbers are plain (5, -2.5). A text value is written as the question writes it.",
        "Late, overdue, behind = finish_moved_wd < 0 or total_float_d < 0, as the question means.",
        "activity_slip, activity_history and simulate_delay take activity_id (as written, C3010); simulate_delay",
        "also takes days. A what-if delay is simulate_delay; any other what-if or advice is `none`.",
        "Omit every field the command does not use.",
    ]
    return "\n".join(lines)


NUMBER = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:[.,]\d+)?")  # not the digits of an ID (X4020); "5j" is 5


def read_choice(reply: dict) -> tools.Choice:
    """Read the model's JSON object as a ``Choice``; a field of the wrong type reads as empty.

    Slips of a small model, seen on real replies, are read as what they say: an Activity ID written
    as a condition (``activity_id = C3010``) is the command's activity; a value of another command,
    or none, is the command's own main value (the sentence names the value answered). ``answer``
    also takes the days of a delay from the question when the reply leaves them out and the
    question writes exactly one number.
    """
    conditions = _conditions(reply)
    command, field = str(reply.get("command", "")), str(reply.get("field", ""))
    argument = str(reply.get("activity_id") or "").strip()
    if command in tools.ACTIVITY_COMMANDS and not argument:
        argument = next((c.value.strip() for c in conditions if c.column == "activity_id" and c.value.strip()), "")
    if command in tools.FIELDS and field not in tools.FIELDS[command]:
        field = tools.FIELDS[command][0]
    days = reply.get("days")
    return tools.Choice(
        command, field, argument, float(days) if isinstance(days, int | float) else 0.0, _query(reply, conditions)
    )


def _conditions(reply: dict) -> tuple[views.Condition, ...]:
    """Read the reply's conditions; an item that is not an object is left out."""
    return tuple(
        views.Condition(str(item.get("column", "")), str(item.get("op", "")), str(item.get("value", "")))
        for item in reply.get("conditions") or []
        if isinstance(item, dict)
    )


def _query(reply: dict, conditions: tuple[views.Condition, ...]) -> views.Query:
    """Read the reply's query: its conditions, sort, limit (``tools.FIRST`` unless a positive number) and grouping."""
    limit = reply.get("limit")
    return views.Query(
        conditions=conditions,
        sort_by=str(reply.get("sort_by") or ""),
        descending=bool(reply.get("descending")),
        limit=int(limit) if isinstance(limit, int | float) and limit > 0 else tools.FIRST,
        group_by=str(reply.get("group_by") or ""),
    )


THINKING_VARIABLE = "XERSCOPE_AGENT_THINKING"
Chat = Callable[[list, dict], dict]


def thinking() -> bool:
    """XERSCOPE_AGENT_THINKING=low: the model reasons first, in a pass of its own (``client.think``)."""
    return os.environ.get(THINKING_VARIABLE, "").strip().lower() == "low"


def answer(
    question: str,
    context: tools.Context,
    lang: str = "en",
    chat: Chat | None = None,
    reason: Callable[[list], str] | None = None,
) -> AgentAnswer:
    """Return the agent's answer to ``question`` on the page's ``context``, in ``lang`` ("en" or "fr").

    ``chat``: called as ``chat(messages, schema)``, the model's JSON object; ``reason``: called as
    ``reason(messages)``, the model's reasoning, handed to ``chat`` with the question. By default the
    local models: the faster one first when XERSCOPE_LLM_FAST_URL names one, the main one when the
    faster one's choice gives no answer; a reasoning pass when XERSCOPE_AGENT_THINKING=low. Raises
    ``client.ModelError`` when no model can be asked.
    """
    if chat is not None:
        return _answer(question, context, lang, (chat, reason), "main")
    fast = client.fast_url()
    if fast:
        said = _answer(question, context, lang, _local(fast), "fast")
        if not said.refused:
            return said
    return _answer(question, context, lang, _local(None), "main")


def _local(url: str | None) -> tuple[Chat, Callable[[list], str] | None]:
    """Return the calls to the local model at ``url`` (the main one for None), reasoning when asked for."""
    reason = (lambda messages: client.think(messages, url)) if thinking() else None
    return (lambda messages, schema: client.complete(messages, schema, url)), reason


def _answer(question: str, context: tools.Context, lang: str, model_calls, model: str) -> AgentAnswer:
    chat, reason = model_calls
    messages = [{"role": "system", "content": system_prompt(context.view)}, {"role": "user", "content": question}]
    started = time.perf_counter()
    reasoning = reason(messages) if reason else ""
    if reasoning:
        messages[1] = {"role": "user", "content": f"{question}\n\nYour notes on it: {reasoning}"}
    choice = _repaired(question, context.view, read_choice(chat(messages, schema_for(context.view))))
    seconds = round(time.perf_counter() - started, 2)
    refusal = _refusal(question, context, choice)
    values = {} if refusal else tools.run(context, choice)
    refusal = refusal or values.get("error", "")
    if refusal:
        return AgentAnswer(choice, values, "", refusal, (), seconds, model, reasoning)
    codes = tuple(values.get("codes") or ([choice.argument] if choice.argument else ()))
    return AgentAnswer(choice, values, sentence(choice, values, lang), "", codes, seconds, model, reasoning)


def _repaired(question: str, view: views.View, choice: tools.Choice) -> tools.Choice:
    """Read the choice's numbers from their text, and a delay's days from the question.

    The days are taken when the reply leaves them out and the question writes exactly one number.
    """
    choice = replace(choice, query=_numbers_of(choice.query, view))
    if choice.command == "simulate_delay" and choice.days <= 0:
        written = [float(n) for n in _numbers(question) if float(n) > 0]
        choice = replace(choice, days=written[0] if len(written) == 1 else 0.0)
    return choice


def _refusal(question: str, context: tools.Context, choice: tools.Choice) -> str:
    """Why the choice gives no answer, "" when it can be run."""
    if choice.command not in tools.FIELDS:
        return "the model chose no known command"
    if choice.command == "none":
        return "these commands cannot answer that question"
    if choice.command in tools.ACTIVITY_COMMANDS and not context.has_activity(choice.argument):
        return f"{choice.argument!r} is not an Activity ID of this update"
    if choice.field == "groups" and not choice.query.group_by:
        return "groups asked without a column to group by"
    reasons = (_condition_refusal(question, context.view, condition) for condition in choice.query.conditions)
    return next((reason for reason in reasons if reason), "")


def _condition_refusal(question: str, view: views.View, condition: views.Condition) -> str:
    """Why a condition is not the question's: a searched word or a number the question does not hold."""
    column = _column(view, condition.column)
    if column is None:
        return ""  # the query says it: no such column
    if column.kind == views.TEXT and not column.values and condition.op in ("contains", "not_contains"):
        held = fold(condition.value) in fold(question)
        return "" if held else f"{condition.value!r} is not a word of the question"  # never invented
    if column.kind == views.NUMBER and condition.value not in _numbers(question):
        return f"{condition.value!r} is not a number of the question"
    return ""


def _column(view: views.View, name: str) -> views.Column | None:
    return next((column for column in view.columns if column.name == name), None)


def _numbers(text: str) -> list[str]:
    """Return the numbers written in ``text``, as plain strings ("5", "-2.5")."""
    return [number.replace(",", ".") for number in NUMBER.findall(text)]


TRUE, FALSE = {"true", "yes", "oui", "vrai", "1"}, {"false", "no", "non", "faux", "0"}


def _numbers_of(query: views.Query, view: views.View) -> views.Query:
    """Read each condition's value as its column's kind says.

    A number condition's value is the first number its text holds ("fmt(5)" -> "5"); a flag compared
    with ``=`` or ``!=`` to a yes or a no ("critical = true", seen with a real model) is ``is_true`` or
    ``is_false``.
    """
    return replace(query, conditions=tuple(_read_as_kind(c, _column(view, c.column)) for c in query.conditions))


def _read_as_kind(condition: views.Condition, column: views.Column | None) -> views.Condition:
    if column is None:
        return condition
    if column.kind == views.NUMBER:
        found = _numbers(condition.value)
        return replace(condition, value=found[0]) if found else condition
    said = condition.value.strip().lower()
    if column.kind == views.FLAG and condition.op in ("=", "!=") and said in TRUE | FALSE:
        holds = (said in TRUE) == (condition.op == "=")
        return replace(condition, op="is_true" if holds else "is_false", value="")
    return condition


LABELS = {  # value -> (English, French)
    "count": ("Activities", "Activités"),
    "list": ("Activities", "Activités"),
    "groups": ("Activities per value", "Activités par valeur"),
    "total_shift_wd": ("Finish moved by (working days, later is negative)", "Fin décalée de (j ouvrés, retard < 0)"),
    "finish_after": ("Finish", "Fin"),
    "driving_predecessors": ("Driving predecessors", "Prédécesseurs pilotes"),
    "finish": ("Finish", "Fin"),
    "first_finish": ("Finish in the first update", "Fin dans la première mise à jour"),
    "updates": ("Updates holding it", "Mises à jour qui la contiennent"),
    "slip_wd": ("Project finish moved by progress (working days)", "Fin projet décalée par l'avancement (j ouvrés)"),
    "replanning_wd": ("Project finish moved by replanning (working days)", "Fin décalée par replanif. (j ouvrés)"),
    "on_path": ("Open activities on the longest path", "Activités ouvertes sur le chemin critique"),
    "entered": ("Activities that entered the longest path", "Activités entrées sur le chemin critique"),
    "left_open": ("Open activities that left the longest path", "Activités ouvertes sorties du chemin critique"),
    "finish_move_wd": ("Project finish would move by (working days)", "La fin projet bougerait de (j ouvrés)"),
    "float_after_d": ("Its total float would be (working days)", "Sa marge totale serait de (j ouvrés)"),
}  # fmt: skip


def sentence(choice: tools.Choice, values: dict, lang: str) -> str:
    """Write the answer from the command's values only."""
    english, french = LABELS[choice.field]
    label = french if lang == "fr" else english
    if choice.command == "query":
        return _query_sentence(choice.field, values, label, lang)
    text = f"{label}: {values[choice.field]}"
    if choice.command == "simulate_delay":
        finish = f"{values['finish_before']} → {values['finish_after']}"
        floats = f"{values['float_before_d']} → {values['float_after_d']}"
        return text + (
            f" (fin {finish}, marge {floats} j)" if lang == "fr" else f" (finish {finish}, float {floats} d)"
        )
    since = values.get("since")
    return text + ((f" (depuis le {since})" if lang == "fr" else f" (since {since})") if since else "")


def _query_sentence(field: str, values: dict, label: str, lang: str) -> str:
    where = " · ".join(values["conditions"]) or ("toutes" if lang == "fr" else "all")
    if field == "groups":
        held = ", ".join(f"{value} {count}" for value, count in list(values["groups"].items())[:10])
        return f"{label}: {held} ({where})"
    if field == "list":
        listed = ", ".join(values["list"]) or ("aucune" if lang == "fr" else "none")
        more = f" … ({values['count']})" if values["count"] > len(values["list"]) else ""
        return f"{label}: {listed}{more} ({where})"
    return f"{label}: {values['count']} ({where})"
