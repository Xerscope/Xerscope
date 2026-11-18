"""Where the elements of a P6 XML export lie, found by searching its bytes instead of parsing every tag.

The elements are its projects, its baselines, its calendars and its resources. P6 writes an export
as plain elements: UTF-8, one namespace declared on the root element, no comment, no CDATA section,
no processing instruction. In such a file every ``<`` opens a start tag or an end tag, so an element
ends at the first end tag of its name after its start tag, and what lies between need not be read.
``scan_export`` reads the children of the root element and, inside a project or a baseline, its own
children. It gives up (``NotPlain``) on anything else it meets: ``pmxml.index_pmxml`` then parses the
whole file.

A wrong end is always met again: the tag that really ends the element comes later, where the search
expects a child or the end of the parent, and it gives up there. What the search does not do is check
the elements it skips: a file damaged inside an activity is indexed all the same. Every element a table
is read from is parsed in full when it is read (``pmxml._document_of``), and refused there.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405 - reads the text of one field, no DOCTYPE reaches it
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple, Protocol

CHUNK_BYTES = 1 << 24
# a start tag: its name (no prefix), its attributes (a value may hold ">"), "/" when the element closes itself
START_TAG = re.compile(rb"<([^\s<>/!?=\"':]+)((?:\s+[^\s<>/=\"']+\s*=\s*(?:\"[^\"<]*\"|'[^'<]*'))*)\s*(/?)>")
DECLARATION = re.compile(rb"(?:\xef\xbb\xbf)?(?:<\?xml\s[^>]*\?>)?")  # a UTF-8 byte order mark, the XML declaration
ENCODING = re.compile(rb"encoding\s*=\s*[\"']([^\"']*)[\"']")
NAMESPACES_DECLARED = re.compile(rb"\s(xmlns(?::[^\s=]+)?)\s*=")
DEFAULT_NAMESPACE = re.compile(rb"\sxmlns\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
# what the search does not read: a comment, a CDATA section or a DOCTYPE; a processing instruction; a namespace
# declared below the root element
NOT_READ = (b"<!", b"<?", b"xmlns")
ROOT = b"APIBusinessObjects"
PROJECT_TAGS = (b"Project", b"BaselineProject")
CALENDAR = b"<Calendar"
AFTER_A_NAME = b" \t\r\n/>"  # the byte after the name in a start tag


class NotPlain(Exception):
    """The file holds something the search does not read: the whole file is to be parsed."""


class FileContents(Protocol):
    """What a file is read through: ``data[first:end]`` gives those bytes (bytes, or ``pmxml.DiskFile``)."""

    def __getitem__(self, span: slice) -> bytes:
        """Return the bytes of a span of the file."""


class Element(NamedTuple):
    """One element the search met; a position is a byte of the file."""

    name: bytes  # blank for the end tag of the element being read
    start: int  # first byte of its start tag
    content: int  # byte after its start tag
    close: int  # first byte of its end tag (``content`` when it closes itself)
    end: int  # byte after its end tag


@dataclass
class ScannedProject:
    """A project or a baseline of the file."""

    tag: str  # Project or BaselineProject
    span: tuple[int, int]
    fields: dict[str, str]  # the first of each listed field among its children
    activities: int


@dataclass
class Scan:
    """What ``scan_export`` found; a span is (first byte of an element, first byte of the tag after it)."""

    namespace: str  # "{uri}", blank without one
    head_end: int = -1  # first byte of the first child of the root element
    tail_start: int = -1  # first byte of the end tag of the root element
    projects: list[ScannedProject] = field(default_factory=list)  # projects and baselines, in the order of the file
    shared_spans: list[tuple[int, int]] = field(default_factory=list)  # each calendar, each resource of the file


class _FileBytes:
    """The bytes of the file from ``first``, read forward a chunk at a time and searched where they lie.

    A position is a byte of the file. What was read stays until ``forget`` drops it.
    """

    def __init__(self, data: FileContents, first: int) -> None:
        """Start at ``first``; nothing is read yet."""
        self.data, self.first = data, first
        self.buffer = bytearray()

    def read_more(self) -> bool:
        """Read the next chunk; False at the end of the file. A chunk the search cannot read stops it."""
        position = self.first + len(self.buffer)
        chunk = self.data[position : position + CHUNK_BYTES]
        if not chunk:
            return False
        joint = bytes(self.buffer[-4:]) + chunk[:4]  # what the end of the buffer cut in two
        if any(pattern in chunk or pattern in joint for pattern in NOT_READ):
            raise NotPlain
        self.buffer += chunk
        return True

    def find(self, pattern: bytes, position: int) -> int:
        """Return the first ``pattern`` from ``position``, reading on until it is met; -1 when there is none."""
        while True:
            found = self.buffer.find(pattern, position - self.first)
            if found >= 0:
                return self.first + found
            position = max(position, self.first + len(self.buffer) - len(pattern) + 1)
            if not self.read_more():
                return -1

    def find_before(self, pattern: bytes, position: int, end: int) -> int:
        """Return the first ``pattern`` between two positions already read; -1 when there is none."""
        found = self.buffer.find(pattern, position - self.first, end - self.first)
        return self.first + found if found >= 0 else -1

    def is_at(self, pattern: bytes, position: int) -> bool:
        """Tell whether the tag at ``position`` starts with ``pattern``."""
        self.find(b">", position)  # the tag is read to its end
        return self.buffer.startswith(pattern, position - self.first)

    def start_tag(self, position: int) -> tuple[bytes, bytes, bool, int]:
        """Read the start tag at ``position``: its name, its attributes, whether it closes itself, the byte after."""
        self.find(b">", position)
        found = START_TAG.match(self.buffer, position - self.first)
        if found is None:
            raise NotPlain
        return found.group(1), found.group(2), bool(found.group(3)), self.first + found.end()

    def between(self, first: int, end: int) -> bytes:
        """Return the bytes between two positions already read."""
        return bytes(self.buffer[first - self.first : end - self.first])

    def byte_at(self, position: int) -> int:
        """Return one byte already read."""
        return self.buffer[position - self.first]

    def read_end(self) -> int:
        """Return the position after the last byte read."""
        return self.first + len(self.buffer)

    def forget(self, position: int) -> None:
        """Drop what lies before ``position``, once that is a chunk or more."""
        if position - self.first >= CHUNK_BYTES:
            del self.buffer[: position - self.first]
            self.first = position


def _next_element(source: _FileBytes, position: int, parent: bytes) -> Element:
    """Read the next child of ``parent`` from ``position``, or the end tag of ``parent`` (blank name)."""
    start = source.find(b"<", position)
    if start < 0:
        raise NotPlain
    if source.is_at(b"</", start):
        if not source.is_at(b"</" + parent + b">", start):
            raise NotPlain
        return Element(b"", start, start, start, start + len(parent) + 3)
    name, _, closes_itself, content = source.start_tag(start)
    if closes_itself:
        return Element(name, start, content, content, content)
    close = source.find(b"</" + name + b">", content)
    if close < 0:
        raise NotPlain
    return Element(name, start, content, close, close + len(name) + 3)


def _children(source: _FileBytes, parent: Element) -> Iterator[Element]:
    """Yield each child of an element read whole, up to the end tag found for it (``parent.close``)."""
    position = parent.content
    while position < parent.close:
        child = _next_element(source, position, parent.name)
        if not child.name:
            return
        yield child
        position = child.end


def _starts_of_calendars(source: _FileBytes, first: int, end: int) -> list[int]:
    """Find where a start tag of a calendar lies between two positions already read."""
    starts, position = [], first
    while (found := source.find_before(CALENDAR, position, end)) >= 0:
        position = found + len(CALENDAR)
        if source.byte_at(position) in AFTER_A_NAME:  # not CalendarObjectId and the like
            starts.append(found)
    return starts


def _calendar_spans(source: _FileBytes, first: int, end: int) -> list[tuple[int, int]]:
    """Find the span of each calendar between two positions already read."""
    spans: list[tuple[int, int]] = []
    for start in _starts_of_calendars(source, first, end):
        calendar = _next_element(source, start, b"")
        if _starts_of_calendars(source, calendar.content, calendar.close):
            raise NotPlain  # a calendar inside a calendar
        spans.append((start, source.find(b"<", calendar.end)))
    return spans


def _text_of(source: _FileBytes, element: Element) -> str:
    """Return the text of a field as a parser gives it: entities read, the blanks around it dropped."""
    if element.close == element.content:
        return ""
    fragment = b"<field>" + source.between(element.content, element.close) + b"</field>"
    try:
        parsed = ET.fromstring(fragment)  # nosec B314 - no DOCTYPE reaches here (NOT_READ): no entity to expand
    except ET.ParseError as error:
        raise NotPlain from error
    return "".join(parsed.itertext()).strip()


def _scan_project(source: _FileBytes, project: Element, listed_fields: tuple[str, ...]) -> ScannedProject:
    """Read the children of a project or baseline: the first of each listed field, how many activities."""
    listed = {name.encode(): name for name in listed_fields}
    fields: dict[str, str] = {}
    activities = 0
    for child in _children(source, project):
        if child.name == b"Activity":
            activities += 1
        elif child.name in listed and listed[child.name] not in fields:
            fields[listed[child.name]] = _text_of(source, child)
    return ScannedProject(project.name.decode(), (project.start, project.end), fields, activities)


def _head(data: FileContents) -> tuple[_FileBytes, Element, str]:
    """Read the declaration and the start tag of the root element: the bytes after it, the root, its namespace."""
    start = bytes(data[:4096])
    declaration = DECLARATION.match(start)
    declared = declaration.group(0) if declaration else b""
    encoding = ENCODING.search(declared)
    if encoding and encoding.group(1).lower() not in (b"utf-8", b"utf8"):
        raise NotPlain
    first = start.find(b"<", len(declared))
    found = START_TAG.match(start, first) if first >= 0 else None
    if found is None or found.group(1) != ROOT or found.group(3):
        raise NotPlain
    if set(NAMESPACES_DECLARED.findall(found.group(2))) - {b"xmlns", b"xmlns:xsi"}:
        raise NotPlain  # a prefix an element of the file may carry
    namespace = DEFAULT_NAMESPACE.search(found.group(2))
    uri = (namespace.group(1) or namespace.group(2) or b"").decode() if namespace else ""
    root = Element(ROOT, first, found.end(), -1, -1)
    return _FileBytes(data, found.end()), root, "{" + uri + "}" if uri else ""


def _keep(scan: Scan, element: Element, project: ScannedProject | None, next_tag: int) -> None:
    """Keep a child of the root element read just before ``next_tag``, where its span ends."""
    if project is not None:
        project.span = (element.start, next_tag)
        scan.projects.append(project)
    elif element.name == b"Resource":
        scan.shared_spans.append((element.start, next_tag))


def scan_export(data: FileContents, listed_fields: tuple[str, ...]) -> Scan:
    """Find the projects, baselines, calendars and resources of a P6 XML export.

    ``listed_fields``: the fields to read of each project and baseline. Raises ``NotPlain`` when the
    file is not written as P6 writes one.
    """
    source, root, namespace = _head(data)
    scan = Scan(namespace)
    position = root.content
    while True:
        child = _next_element(source, position, ROOT)
        if scan.head_end < 0:
            scan.head_end = child.start
        if not child.name:
            break
        project = _scan_project(source, child, listed_fields) if child.name in PROJECT_TAGS else None
        scan.shared_spans += _calendar_spans(source, child.start, child.end)
        _keep(scan, child, project, source.find(b"<", child.end))
        position = child.end
        source.forget(child.start)
    scan.tail_start = child.start
    while source.read_more():
        pass
    if source.between(child.end, source.read_end()).strip():
        raise NotPlain  # something after the root element
    scan.shared_spans.sort(key=lambda span: span[1])  # as the elements end, a calendar before what holds it
    return scan
