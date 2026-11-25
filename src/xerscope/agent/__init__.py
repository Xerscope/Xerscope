"""The Gantt Ask field's local agent, off unless XERSCOPE_AGENT=on (docs/deploy.md §12).

The keyword grammar answers first (analysis/ask); a sentence it does not fully read goes to the local
model, which chooses one command of ``tools.FIELDS`` and one of its values under a JSON schema. xerscope
runs the command and writes the sentence itself from a template: every Activity ID, date and number of
the answer is a value a command computed. A choice outside the lists, an Activity ID the update does not
hold or a command that cannot be read gives no answer, said as such. ``client`` is the only module of
xerscope that opens a connection, to the local model only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from . import client, tools


@dataclass(frozen=True)
class AgentAnswer:
    """What the agent said, and how.

    The command and value chosen, the argument, the values the command computed, the sentence written
    from them (empty with ``refused``) and the time the model took.
    """

    command: str
    field: str
    argument: str
    values: dict
    sentence: str
    refused: str
    seconds: float


ALL_FIELDS = sorted({field for fields in tools.FIELDS.values() for field in fields})
SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "enum": list(tools.FIELDS)},
        "field": {"type": "string", "enum": ALL_FIELDS},
        "argument": {"type": "string"},
    },
    "required": ["command", "field", "argument"],
    "additionalProperties": False,
}

LABELS = {  # field -> (English, French) words the sentence starts with
    "task_code": ("Activity found", "Activité trouvée"),
    "count": ("Activities matching", "Activités correspondantes"),
    "task_codes": ("Activities", "Activités"),
    "total_shift_wd": ("Finish moved by (working days, lost negative)", "Fin décalée de (j ouvrés, perte négative)"),
    "finish_after": ("Finish now", "Fin actuelle"),
    "driving_predecessors": ("Driving predecessors", "Prédécesseurs pilotes"),
    "finish": ("Finish", "Fin"),
    "first_finish": ("Finish in the first update", "Fin dans la première mise à jour"),
    "updates": ("Updates holding it", "Mises à jour qui la contiennent"),
    "slip_wd": ("Project finish moved by progress (working days)", "Fin projet décalée par l'avancement (j ouvrés)"),
    "replanning_wd": (
        "Project finish moved by replanning (working days)",
        "Fin projet décalée par replanification (j ouvrés)",
    ),
    "on_path": ("Open activities on the longest path", "Activités ouvertes sur le chemin critique"),
    "entered": ("Activities that entered the longest path", "Activités entrées sur le chemin critique"),
    "left_open": ("Open activities that left the longest path", "Activités ouvertes sorties du chemin critique"),
}  # fmt: skip


VALUES = {  # field -> what it answers, as the model reads it
    "task_code": "the one Activity ID found",
    "count": "how many",
    "task_codes": "which activities",
    "total_shift_wd": "working days the activity's finish moved",
    "finish_after": "the activity's finish now",
    "driving_predecessors": "what drives the activity",
    "finish": "the finish date now",
    "first_finish": "the finish in the first update",
    "updates": "in how many updates",
    "slip_wd": "working days the project finish moved because of the week's progress",
    "replanning_wd": "working days the project finish moved because of replanning",
    "on_path": "how many open activities are on the longest path",
    "entered": "how many activities entered the longest path",
    "left_open": "how many open activities left the longest path",
}


def system_prompt() -> str:
    """Return the model's instructions: the commands, what each of their values means, the argument."""
    lines = [
        "You route a question about a construction schedule to ONE command and ONE of its values.",
        "Reply with JSON only.",
        "Commands (argument after the colon):",
    ]
    for command, (what, argument) in tools.COMMANDS.items():
        lines.append(f"- {command}: {what}. Argument: {argument or 'empty'}.")
        lines += [f"    - {field}: {VALUES[field]}" for field in tools.FIELDS[command] if field in VALUES]
    lines += [
        "Critical, near critical, late, not started, in progress, completed, milestones, a WBS or a resource",
        "are filters: `filter`, even with the word critical. The longest path is `path_changes` only.",
        "A question naming an Activity ID (C3010) and a move, a slip or a delay is `activity_slip`.",
        "A what-if, a simulation or a fact the schedule does not hold is `none`.",
    ]
    return "\n".join(lines)


def answer(
    question: str, context: tools.Context, lang: str = "en", chat: Callable[[list, dict], dict] | None = None
) -> AgentAnswer:
    """Return the agent's answer to ``question`` on the page's ``context``, in ``lang`` ("en" or "fr").

    ``chat``: called as ``chat(messages, schema)``, the model's JSON object; ``client.complete`` by default.
    Raises ``client.ModelError`` when the model cannot be asked.
    """
    chat = chat or client.complete
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": question}]
    started = time.perf_counter()
    chosen = chat(messages, SCHEMA)
    seconds = round(time.perf_counter() - started, 2)
    command, field = str(chosen.get("command", "")), str(chosen.get("field", ""))
    argument = str(chosen.get("argument", "")).strip()
    if command == "filter":  # the grammar reads the user's own words, never the model's rewording
        argument = question

    def refuse(reason: str, values: dict | None = None) -> AgentAnswer:
        return AgentAnswer(command, field, argument, values or {}, "", reason, seconds)

    if command not in tools.FIELDS:
        return refuse("the model chose no known command")
    if command == "none":
        return refuse("these commands cannot answer that question (a what-if, or a fact the schedule does not hold)")
    if field == "none":  # a command with no value named: the command's first, its main one
        field = tools.FIELDS[command][0]
    if field not in tools.FIELDS[command]:
        return refuse(f"{field!r} is not a value of {command}")
    if command in tools.ACTIVITY_COMMANDS and not context.has_activity(argument):
        return refuse(f"{argument!r} is not an Activity ID of this update")
    values = tools.run(context, command, argument)
    if "error" in values:
        return refuse(values["error"], values)
    return AgentAnswer(command, field, argument, values, sentence(field, values, lang), "", seconds)


def sentence(field: str, values: dict, lang: str) -> str:
    """Write the answer from the command's values only."""
    english, french = LABELS[field]
    value = values[field]
    if isinstance(value, list):
        value = ", ".join(value) or ("none" if lang != "fr" else "aucune")
    if value is None:
        value = "several or none: see the list" if lang != "fr" else "plusieurs ou aucune : voir la liste"
    since = values.get("since")
    when = (f" (depuis le {since})" if lang == "fr" else f" (since {since})") if since else ""
    return f"{french if lang == 'fr' else english}: {value}{when}"
