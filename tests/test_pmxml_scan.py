"""The index of a P6 XML export found by searching its bytes (xer/pmxml_scan.py) is the index the
full pass makes (pmxml._index_by_parsing), or the search gives up and the full pass is made.

Files built in code. The full pass is the reference: it parses every tag of the file.
"""

import random

import pytest
from pmxmlkit import NAMESPACE, _fields, activity, baseline, calendar

from xerscope.xer import XerError, pmxml_scan
from xerscope.xer.pmxml import (
    LISTED_FIELDS,
    DiskFile,
    _index_by_parsing,
    _index_of,
    index_pmxml,
    read_pmxml_baseline,
)
from xerscope.xer.pmxml_scan import NotPlain, scan_export

ROOT = f'<APIBusinessObjects xmlns="{NAMESPACE}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
PLANNED = activity("A1", "11", "2026-03-02T08:00:00", "2026-03-06T17:00:00", 40)


def export(body: str, head: str = '<?xml version="1.0" encoding="UTF-8"?>', tail: str = "") -> bytes:
    return f"{head}{ROOT}{body}</APIBusinessObjects>{tail}".encode()


def project(object_id: str, *children: str, **fields: str) -> str:
    return f"<Project>{_fields({'ObjectId': object_id, **fields})}{''.join(children)}</Project>"


PLAIN = {
    "a project and its baseline": export(
        calendar() + project("1", CurrentBaselineProjectObjectId="101") + baseline("101", "B1", [PLANNED])
    ),
    "calendars inside a project, a baseline and a resource; other elements of the file": export(
        "<Currency><ObjectId>1</ObjectId><Name>Euro</Name></Currency>\n"
        + calendar("8")
        + "<Resource><ObjectId>3</ObjectId><Name>Crew</Name>"
        + calendar("9", "Crew calendar")
        + "</Resource>\r\n"
        + project("1", calendar("21", "Of the project"), PLANNED, DataDate="2026-03-02T08:00:00")
        + baseline("101", "B1", [calendar("31", "Of the baseline"), PLANNED, PLANNED])
        + "<Resource><ObjectId>4</ObjectId></Resource>"
    ),  # fmt: skip
    "fields that close themselves, entities and accents, an attribute that holds a tag end": export(
        "<Project><ObjectId>1</ObjectId><DataDate/><Name>R&amp;D caf&#233; été</Name>"
        '<DateAdded xsi:nil="true"/><Id note="a>b">P &lt; 1</Id><WBS><Name>below the project</Name></WBS></Project>'
        "<BaselineProject>\n  <ObjectId> 101 </ObjectId>\n  <Activity/>\n  <Calendar/>\n</BaselineProject>\n"
    ),
    "a field met twice, a field after the activities, two baselines of one id": export(
        "<Project><ObjectId>1</ObjectId><ObjectId>2</ObjectId>" + PLANNED + "<DataDate>2026-03-02T08:00:00</DataDate>"
        "</Project>" + baseline("101", "B1", [PLANNED]) + baseline("101", "B1 again", [PLANNED, PLANNED])
    ),
    "no declaration, blanks around every element": export(
        "\n  " + calendar() + "\n  " + project("1") + "\n  " + baseline("101", "B1", [PLANNED]) + "\n", head=""
    ),
    "a byte order mark": export(project("1") + baseline("101", "B1", [PLANNED]), head='﻿<?xml version="1.0"?>'),
    "nothing in the file": export(""),
    "a root element without a namespace": b"<APIBusinessObjects><Project><ObjectId>1</ObjectId></Project>"
    b"</APIBusinessObjects>\n",
}


@pytest.mark.parametrize("case", PLAIN)
def test_a_file_written_as_p6_writes_one_is_indexed_by_the_search_as_by_the_full_pass(case):
    data = PLAIN[case]
    assert _index_of(scan_export(data, LISTED_FIELDS)) == _index_by_parsing(data, "export.xml")


def test_the_spans_and_the_fields_the_search_finds_are_those_written_in_the_file():
    """One calendar, one project, one baseline of two activities: positions read in the bytes themselves."""
    data = export(
        calendar() + project("1", CurrentBaselineProjectObjectId="101") + baseline("101", "B1", [PLANNED] * 2)
    )
    scan = scan_export(data, LISTED_FIELDS)
    found_project, found_baseline = scan.projects
    assert scan.namespace == "{" + NAMESPACE + "}"
    assert (scan.head_end, scan.tail_start) == (data.index(b"<Calendar>"), data.index(b"</APIBusinessObjects>"))
    assert scan.shared_spans == [(data.index(b"<Calendar>"), data.index(b"<Project>"))]
    assert found_project.fields == {"ObjectId": "1", "CurrentBaselineProjectObjectId": "101"}
    assert found_baseline.span == (data.index(b"<BaselineProject>"), data.index(b"</APIBusinessObjects>"))
    assert (found_baseline.tag, found_baseline.activities) == ("BaselineProject", 2)
    assert found_baseline.fields["Id"] == "B1" and found_baseline.fields["DataDate"] == "2026-02-23T08:00:00"


def one_baseline(planned: str) -> bytes:
    return export(baseline("101", "B1", [planned]))


NOT_PLAIN = {
    "a comment": export(project("1") + "<!-- exported on Monday -->"),
    "a comment that holds an end tag": one_baseline(PLANNED.replace("</Id>", "</Id><!-- </Activity> -->")),
    "a comment that holds a calendar, inside an activity": one_baseline(
        PLANNED.replace("</Id>", f"</Id><!--{calendar()}-->")
    ),
    "a CDATA section": export("<Project><ObjectId>1</ObjectId><Name><![CDATA[<Calendar>]]></Name></Project>"),
    "a CDATA section that holds a calendar, inside an activity": one_baseline(
        PLANNED.replace("</Id>", "</Id><Notes><![CDATA[<Calendar/>]]></Notes>")
    ),
    "a processing instruction": export(project("1") + "<?layout wide?>"),
    "a processing instruction that holds a calendar, inside an activity": one_baseline(
        PLANNED.replace("</Id>", "</Id><?layout <Calendar/> ?>")
    ),
    "a DOCTYPE": export(project("1"), head='<?xml version="1.0"?><!DOCTYPE APIBusinessObjects>'),
    "a prefix declared on the root element": export(project("1")).replace(b"xmlns:xsi", b"xmlns:p6"),
    "a namespace declared below the root element": export('<Calendar xmlns="urn:another"/>'),
    "a namespace that is not UTF-8": b'<APIBusinessObjects xmlns="\x80">',
    "a namespace written with an entity": export(baseline("101", "B1", [PLANNED])).replace(
        NAMESPACE.encode(), b"urn:p6&amp;api"
    ),
    "a namespace written with a tab": export(baseline("101", "B1", [PLANNED])).replace(
        NAMESPACE.encode(), b"urn:p6\tapi"
    ),
    "another encoding": export(project("1"), head='<?xml version="1.0" encoding="ISO-8859-1"?>'),
    "UTF-16": export(project("1"), head='<?xml version="1.0" encoding="UTF-16"?>').decode().encode("utf-16"),
    "an activity inside an activity": one_baseline(PLANNED.replace("</Activity>", PLANNED + "</Activity>")),
    "a project inside a project": export(project("1", project("2"))),
    "a calendar inside a calendar": export(calendar().replace("</Calendar>", "<Calendar/></Calendar>")),
    "an end tag written with a blank": export(project("1", PLANNED.replace("</Activity>", "</Activity >"))),
    "a start tag that is not one": export(project("1") + "< Project/>"),
    "text after the root element": export(project("1"), tail="exported"),
    "another root element": b"<Projects><Project><ObjectId>1</ObjectId></Project></Projects>",
    "a file cut short": export(project("1") + baseline("101", "B1", [PLANNED]))[:-40],
}  # fmt: skip


def index_or_refusal(read, data: bytes):
    try:
        return read(data, "export.xml")
    except XerError as refusal:
        return str(refusal)


@pytest.mark.parametrize("case", NOT_PLAIN)
def test_the_search_gives_up_on_what_it_does_not_read_and_the_file_is_parsed_whole(case):
    data = NOT_PLAIN[case]
    with pytest.raises(NotPlain):
        scan_export(data, LISTED_FIELDS)
    assert index_or_refusal(index_pmxml, data) == index_or_refusal(_index_by_parsing, data)


# --- CDATA sections: P6 writes them (the Id and Name of a project in an export of P6 20.12) -----------


def in_section(text: str) -> str:
    return f"<![CDATA[{text}]]>"


NAMED_IN_SECTIONS = PLANNED.replace("<Name>A1</Name>", f"<Name>{in_section('Pour <slab> & cure')}</Name>")
SECTIONS = {
    "the Id and Name of a project, a baseline and an activity, as P6 20.12 writes them": export(
        calendar()
        + project("1", Id=in_section("UPD"), Name=in_section("Update"), CurrentBaselineProjectObjectId="101")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        + baseline("101", "B1", [NAMED_IN_SECTIONS, PLANNED]).replace("<Id>B1</Id>", f"<Id>{in_section('B1')}</Id>")
    ),
    "a section that holds the end tag of its own field": export(
        f"<Project><ObjectId>1</ObjectId><Name>{in_section('a</Name>b')}</Name><Id>P1</Id></Project>"
    ),
    "a section that holds the end tag of its project and a start tag of a baseline": export(
        f"<Project><ObjectId>1</ObjectId><Name>{in_section('x</Project><BaselineProject>y')}</Name></Project>"
        + baseline("101", "B1", [PLANNED])
    ),
    "a section of an activity that holds an activity and the end tag of its baseline": one_baseline(
        PLANNED.replace("</Id>", f"</Id><Notes>{in_section('<Activity>n</Activity></BaselineProject>')}</Notes>")
    ).replace(b"</BaselineProject>", (PLANNED + "</BaselineProject>").encode()),
    "two sections in one field, two closing brackets inside one, an empty one": export(
        f"<Project><ObjectId>1</ObjectId><Name>{in_section('a]]b')}{in_section('')}{in_section('c')}</Name></Project>"
    ),
    "a section that holds what an entity or a tag would be": export(
        f"<Project><ObjectId>1</ObjectId><Name>{in_section('R&amp;D <b>bold</b> &#233;')}</Name></Project>"
    ),
    "text around a section, in a listed field": export(
        f"<Project><ObjectId> {in_section('1')} </ObjectId><Id>P{in_section('-')}1</Id></Project>"
    ),
    "a section in the last field of the file": export(
        project("1") + f"<Currency><Name>{in_section('Euro</Currency>')}</Name></Currency>"
    ),
}
STILL_NOT_READ = {
    "a section never closed": export("<Project><ObjectId>1</ObjectId><Name><![CDATA[open</Name></Project>"),
    "a section between two children of a project": export(
        f"<Project><ObjectId>1</ObjectId>{in_section('loose')}<Id>P1</Id></Project>"
    ),
    "a section between two children of the root element": export(project("1") + in_section("loose")),
    "what looks like a section but is not one": export(project("1", Name="x") + "<![cdata[n]]>"),
    "a comment beside a section": export(
        f"<Project><ObjectId>1</ObjectId><Name>{in_section('n')}</Name><!-- note --></Project>"
    ),
}


@pytest.mark.oracle("property")
@pytest.mark.parametrize("chunk_bytes", [1, 2, 3, 5, 7, 8, 9, 11, 1 << 24])
@pytest.mark.parametrize("case", SECTIONS)
def test_a_cdata_section_is_read_as_the_text_it_holds(case, chunk_bytes, monkeypatch):
    """What a section holds is text, whatever it looks like: the search does not give up on it and
    finds the index of the full pass. Read a few bytes at a time, each mark of a section is cut by
    the end of what was read."""
    monkeypatch.setattr(pmxml_scan, "CHUNK_BYTES", chunk_bytes)
    data = SECTIONS[case]
    assert _index_of(scan_export(data, LISTED_FIELDS)) == _index_by_parsing(data, "export.xml")


@pytest.mark.oracle("property")
def test_the_text_of_a_section_is_the_one_the_file_holds():
    """Written by hand: the fields of a project named in sections, and the count of its activities."""
    data = SECTIONS["the Id and Name of a project, a baseline and an activity, as P6 20.12 writes them"]
    found_project, found_baseline = scan_export(data, LISTED_FIELDS).projects
    assert (found_project.fields["Id"], found_project.fields["Name"]) == ("UPD", "Update")
    assert (found_baseline.fields["Id"], found_baseline.activities) == ("B1", 2)
    odd = SECTIONS["two sections in one field, two closing brackets inside one, an empty one"]
    assert scan_export(odd, LISTED_FIELDS).projects[0].fields["Name"] == "a]]bc"
    literal = SECTIONS["a section that holds what an entity or a tag would be"]
    assert scan_export(literal, LISTED_FIELDS).projects[0].fields["Name"] == "R&amp;D <b>bold</b> &#233;"


@pytest.mark.oracle("property")
def test_an_export_with_sections_is_indexed_without_the_full_pass(monkeypatch):
    """The reason for reading them: the full pass parses every tag of a file that runs to gigabytes."""
    data = SECTIONS["the Id and Name of a project, a baseline and an activity, as P6 20.12 writes them"]
    expected = _index_by_parsing(data, "export.xml")

    def full_pass(*arguments):
        raise AssertionError("the full pass was made")

    monkeypatch.setattr("xerscope.xer.pmxml._index_by_parsing", full_pass)
    index = index_pmxml(data, "export.xml")
    assert index == expected
    read = read_pmxml_baseline(data, "export.xml", "101", index)
    assert read.tables["PROJECT"]["proj_short_name"].tolist() == ["B1"]
    assert sorted(read.tables["TASK"]["task_name"]) == ["A1", "Pour <slab> & cure"]


@pytest.mark.oracle("property")
@pytest.mark.parametrize("case", STILL_NOT_READ)
def test_the_search_still_gives_up_on_a_section_it_cannot_place(case):
    data = STILL_NOT_READ[case]
    with pytest.raises(NotPlain):
        scan_export(data, LISTED_FIELDS)
    assert index_or_refusal(index_pmxml, data) == index_or_refusal(_index_by_parsing, data)


SECTION_TEXTS = [
    in_section("n"), in_section("a</Name>b"), in_section("</Project>"), in_section("x]]y"), in_section("<Activity>"),
    in_section(""), "a" + in_section("&amp;") + "b", in_section("</BaselineProject><Resource>"),
]  # fmt: skip


@pytest.mark.oracle("property")
@pytest.mark.parametrize("chunk_bytes", [7, 1 << 24])
def test_on_random_files_with_sections_the_search_gives_the_index_of_the_full_pass_or_gives_up(
    chunk_bytes, monkeypatch
):
    """1 500 files whose texts are sections half of the time, some holding tags of the index. The search
    reads most of them (it gave up on every one before sections were read), never differently."""
    monkeypatch.setattr(pmxml_scan, "CHUNK_BYTES", chunk_bytes)
    monkeypatch.setitem(globals(), "TEXTS", [*TEXTS[:8], *SECTION_TEXTS])
    same = with_sections = 0
    for seed in range(1500):
        data = random_file(seed)
        try:
            searched = _index_of(scan_export(data, LISTED_FIELDS))
        except NotPlain:
            continue
        parsed = index_or_refusal(_index_by_parsing, data)
        if isinstance(parsed, str):
            continue
        assert searched == parsed, (seed, data)
        same += 1
        with_sections += b"<![CDATA[" in data
    assert same > 300 and with_sections > 100, (same, with_sections)


# --- random files: the search never gives another index than the full pass ---------------------------

NAMES = [
    "Project", "BaselineProject", "Calendar", "Resource", "Activity", "ObjectId", "Id", "Name", "DataDate",
    "DateAdded", "OriginalProjectObjectId", "CurrentBaselineProjectObjectId", "WBS", "CalendarObjectId", "Code",
]  # fmt: skip
TEXTS = ["", "12", "A &amp; B", "caf&#233;", "  7  ", "2026-03-02T08:00:00", "x > y", "été", "Calendar", "a 'b' \"c\""]
ODD = [
    "<!-- note -->", "<!-- </Activity> -->", "<![CDATA[<Calendar>]]>", "<?layout <Project> ?>",
    '<Calendar xmlns="urn:another"/>', "</Activity >", "<Activity >x</Activity>", '<Name a="1>2">n</Name>',
    "<Name\n  a='x'>n</Name>", "<Id/>", '<DataDate xsi:nil="true"/>',
]  # fmt: skip


def random_element(rnd: random.Random, depth: int, odd_rate: float) -> str:
    """An element with up to five levels below the root, of the names the index reads and a few others."""
    if rnd.random() < odd_rate:
        return rnd.choice(ODD)
    name = rnd.choice(NAMES if depth > 1 else [*NAMES[:6], "Other"])
    if depth >= 5 or rnd.random() < 0.35:
        text = rnd.choice(TEXTS)
        return f"<{name}/>" if not text and rnd.random() < 0.5 else f"<{name}>{text}</{name}>"
    children = [
        rnd.choice(["", "\n  ", " "]) + random_element(rnd, depth + 1, odd_rate) for _ in range(rnd.randint(0, 6))
    ]
    return f"<{name}>{''.join(children)}{rnd.choice(['', chr(10)])}</{name}>"


def random_file(seed: int) -> bytes:
    rnd = random.Random(seed)
    odd_rate = rnd.choice([0, 0, 0, 0.03])
    head = rnd.choice(
        ['<?xml version="1.0" encoding="UTF-8"?>', "<?xml version='1.0'?>\n", "", '﻿<?xml version="1.0"?>']
    )
    root = rnd.choice([ROOT, ROOT, "<APIBusinessObjects>"])
    children = [rnd.choice(["", "\r\n", "  "]) + random_element(rnd, 1, odd_rate) for _ in range(rnd.randint(0, 8))]
    return f"{head}{root}{''.join(children)}</APIBusinessObjects>{rnd.choice(['', chr(10)])}".encode()


@pytest.mark.parametrize("chunk_bytes", [7, 1 << 24])
def test_on_random_files_the_search_gives_the_index_of_the_full_pass_or_gives_up(chunk_bytes, monkeypatch):
    """1 500 files; read 7 bytes at a time, every tag is cut by the end of what was read. A file the full
    pass refuses is not well formed: the search may index it (the module says why), never differently."""
    monkeypatch.setattr(pmxml_scan, "CHUNK_BYTES", chunk_bytes)
    same = with_projects = with_shared_spans = 0
    for seed in range(1500):
        data = random_file(seed)
        try:
            searched = _index_of(scan_export(data, LISTED_FIELDS))
        except NotPlain:
            continue
        parsed = index_or_refusal(_index_by_parsing, data)
        if isinstance(parsed, str):
            continue
        assert searched == parsed, (seed, data)
        same += 1
        with_projects += bool(parsed.projects or parsed.baselines)
        with_shared_spans += bool(parsed.shared_spans)
    assert same > 300 and with_projects > 80 and with_shared_spans > 100, (same, with_projects, with_shared_spans)


def test_a_file_of_the_disk_is_searched_a_chunk_at_a_time_and_what_was_searched_is_dropped(tmp_path, monkeypatch):
    """A file of three baselines read 200 bytes at a time: the same index, and the bytes kept never hold the
    whole file (a baseline here is about 1 500 bytes, the file about 5 000)."""
    data = PLAIN["calendars inside a project, a baseline and a resource; other elements of the file"]
    data = data.replace(
        b"</APIBusinessObjects>", (baseline("102", "B2", [PLANNED]) * 2).encode() + b"</APIBusinessObjects>"
    )
    path = tmp_path / "export.xml"
    path.write_bytes(data)
    monkeypatch.setattr(pmxml_scan, "CHUNK_BYTES", 200)
    kept: list[int] = []
    forget = pmxml_scan._FileBytes.forget

    def measured(self, position):
        forget(self, position)
        kept.append(len(self.buffer))

    monkeypatch.setattr(pmxml_scan._FileBytes, "forget", measured)
    assert index_pmxml(DiskFile(path), "export.xml") == _index_by_parsing(data, "export.xml")
    assert len(data) > 4000 and max(kept) < len(data) / 2


def test_a_file_damaged_inside_an_activity_is_indexed_and_refused_when_its_baseline_is_read():
    """What the search skips it does not check: the full pass refuses the file, the search lists its
    baseline, and reading that baseline, which parses it in full, refuses it."""
    damaged = export(baseline("101", "B1", [PLANNED.replace("</Name>", "</Nom>")]))
    with pytest.raises(XerError, match="not a readable P6 XML file"):
        _index_by_parsing(damaged, "export.xml")
    index = index_pmxml(damaged, "export.xml")
    assert [(listed.object_id, listed.activities) for listed in index.baselines] == [("101", 1)]
    with pytest.raises(XerError):
        read_pmxml_baseline(damaged, "export.xml", "101", index)
