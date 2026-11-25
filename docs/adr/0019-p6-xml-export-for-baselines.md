# ADR-0019: P6 XML (PMXML) export read for baselines, streamed and converted to the XER tables

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-06 (`b20a0b8`, #138: baselines read from a P6 XML export); the index found by searching the bytes from 2026-11-18 (`eb6e15f`, #287); the resolution of each update from 2026-11-18 (`92109b2`, #281); the `baselines` subfolder from 2026-11-23 (`a3ee467`) |
| Scope | `src/xerscope/xer/pmxml.py`, `xer/pmxml_scan.py`, `xer/__init__.py` (`load_snapshot`, `pmxml_files`); `src/xerscope/analysis/baseline_resolution.py`, `analysis/baseline.py` (`content_digest`); `src/xerscope/app/baseline_export.py`, `app/baseline_file.py`, `app/xml_baselines.py`, `app/baselines.py` (`_resolved_baseline`, `_chosen_baseline`) |
| Sources | Oracle, P6 Professional help, Export to XML, "Baselines to Export" (P6 Professional exports no project baseline in XER); P6 EPPM Web Services reference, Project Fields (`CurrentBaselineProjectObjectId`: "the project's baseline to use for computing summaries"); P6 Professional help, "Copy Project Options dialog box" and "Create a baseline"; MPXJ's P6 XML reader (the conversions); `b20a0b8` "Baselines from a P6 XML export: each update measured against the baseline its file names (#138)"; `eb6e15f` "P6 XML baseline file: its index is found by searching the bytes, not by parsing every tag (#287)"; `92109b2` "Baselines: the Debug page shows the baseline each update would be measured against (#281)"; `c30d060` "P6 XML baseline file: the search for its index reads CDATA sections (#322)"; `ea3ea52` "test(pmxml): the P6 XML reader against the XER reader on projects P6 exported in both formats"; `a3ee467` "Offer the baseline files of a baselines subfolder as the separate baseline"; [docs/architecture.md §5](../architecture.md) "Baseline sources"; [CHANGELOG.md](../../CHANGELOG.md) [Unreleased] |

## Context

Each update of a series names its Project Baseline (`PROJECT.sum_base_proj_id`) but its XER
usually does not hold it: P6 Professional does not export a project's baselines in XER; its XML
export does ("Baselines to Export", one tick per baseline). A series whose Project Baseline
changed over time names several baselines.

Two further facts shape the reading:

- An XML export of several projects with all their baselines runs to gigabytes. Parsing it as one
  `ElementTree` would hold the whole file in memory on a NAS with a memory cap (docs/deploy.md §7).
- Where the planner keeps one copy of the project per version, each copy carries its own copy of
  the baseline in force under a new id ("Copy Project Options": "Baselines: Mark this checkbox to
  copy baselines to the new project"). The export of the versions still in the database then holds
  the same baseline several times, and may not hold the copy an older update names.

Every analysis already reads the XER tables through `build_snapshot` (ADR-0002); a baseline must
be analysed the same way whatever format it came from.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Ask the user for one baseline XER per baseline | none in code | P6 Professional does not export baselines in XER: the user would first have to restore each baseline as a project |
| Read the XML into a second model beside the XER one | a second set of P6 meanings | two models to keep equal; every analysis would need two paths |
| **Convert each `BaselineProject` to the XER tables `build_snapshot` reads, with MPXJ's conversions; index the file once by searching its bytes and read one baseline's bytes alone (chosen)** | a converter per table and a byte-level scanner | fields a baseline is never read for are left out (GUID, longest path flag, WBS earned value technique); a file not written as P6 writes one falls back to a full parse |

## Decision

**One conversion to the XER tables.** `xer/pmxml.py:read_pmxml_baseline` turns one
`BaselineProject` element into the tables `build_snapshot` reads: PROJECT, PROJWBS, TASK,
TASKPRED, TASKRSRC, PROJCOST, CALENDAR, RSRC, and returns a `RawXer`. The conversions are MPXJ's:

- durations and units in hours;
- percentages as fractions in XML, times 100 in XER (`_percent`);
- names of types and statuses spelled out in XML, mapped to the XER codes (`ACTIVITY_STATUS`,
  `ACTIVITY_TYPE`, `PERCENT_COMPLETE_TYPE`, `CONSTRAINT_TYPE`, `RELATIONSHIP_TYPE`,
  `RESOURCE_TYPE`, `CALENDAR_TYPE`);
- calendar work periods end on their last working minute in XML ("11:59") and on the next minute
  in XER ("12:00"); `clndr_data` dates are Excel serial numbers (`EXCEL_EPOCH`).

`load_snapshot(data, name=, project_id=)` recognises a P6 XML file (`is_pmxml`) and reads one of
its baselines, `project_id` naming it, so a baseline read from XML is analysed exactly as one read
from XER. `choose_baseline` takes the baseline asked for (an update's `sum_base_proj_id`; absent is
a refusal, never another in its place), else the project's `CurrentBaselineProjectObjectId`, else
the only one; several and none named is refused with the list. A relationship naming another
project as successor is counted in the notes, not silently lost. A value P6 would not write raises
`XerError` (the load contract, ADR-0002).

**The file is never held as one tree.** `index_pmxml(data, source)` goes through the export once
and keeps, for each baseline, what lists it (`XmlBaseline`: object id, code, name, data date,
original project, activity count) and where its bytes are (`baseline_spans`), with the projects'
Project Baseline pointers (`XmlProject`). It searches the bytes (`pmxml_scan.scan_export`) instead
of parsing every tag: P6 writes plain elements (UTF-8, one namespace on the root, no comment, no
processing instruction), so outside a CDATA section every `<` opens a tag and an element ends at
the first end tag of its name. CDATA sections (P6 Professional 20.12 writes some Id and Name
fields so) are read as the text of a field (`c30d060`). On anything else the scan gives up
(`NotPlain`) and `_index_by_parsing` parses the whole file with expat, 16 MB at a time
(`PARSE_CHUNK_BYTES`), giving the same index. `read_pmxml_baseline` then parses only the head of
the file, that baseline's span and the shared calendars and resources (`_document_of`). Both
functions take the bytes or a `DiskFile`, which reads only the slices asked from the disk; a file
cut or gone since its index is a `XerError`.

**Which baseline each update is measured against.** `analysis/baseline_resolution.py:resolution`
looks, in this order: in the update's own file (`IN_FILE`); in the export, under the id the update
names (`IN_EXPORT`, exact); among the loaded updates, when the id names the project another file
was exported from (`LOADED_UPDATE`, probable); in the export, between the versions created just
before and just after the update's project (ordered by ObjectId), when their Project Baselines
have the same content (`SAME_GENERATION`, probable; `analysis.baseline.content_digest` compares
two copies stored under different ids). When those versions hold different baselines, or the
export has no version on one side of the update's project, the update is `UNDECIDED`: nothing is applied until the user picks a candidate or the fallback in the window
(ADR-0018). It is `NOT_FOUND` when no project of the export names a baseline it holds, or when the
project id is not a number (no order of creation to read). Only the first two are what P6 itself
measured against.
`app/baseline_export.py` holds the export in use (`baseline_export`, `export_contents`,
`_resolution`, `_export_baseline` read once per baseline and basis, `is_undecided`,
`candidates`); `app/xml_baselines.py` lays the export's baselines against what each update names
for the window and the Debug page (`xml_baselines_table`, `resolution_table`,
`baseline_per_file`).

**Where a baseline file comes from.** The separate baseline file (`app/baseline_file.py`) is
uploaded, named by `XERSCOPE_BASELINE` (or `xerscope app --baseline`, XER or P6 XML), or picked in
the updates' folder: the P6 XML exports next to the updates, then every .xer and P6 XML file of the
`baselines` subfolder (`BASELINES_FOLDER`), listed as "baselines/<name>". The updates are read
from the folder's .xer files only, never from its subfolders, so a baseline exported as its own
XER can sit there even under the name of an update.

## Consequences

Positive:

- Each update is measured against the baseline its file names, as P6 measured it, even when the
  XER does not hold it.
- A baseline read from XML gives the same snapshot and planned value as the same baseline read
  from XER (checked on projects P6 exported in both formats).
- Memory stays at one baseline's size plus the index, whatever the size of the export.

Negative:

- The ObjectId order of versions is what the databases seen so far show; Oracle does not document
  it (`baseline_resolution.py` docstring). The two probable kinds are marked as such on every
  page, warning and download.
- Building a file's baseline re-reads the export per session and keeps its bytes in the session
  ([docs/backlog.md](../backlog.md), "App").
- The scan does not check what it skips (the elements between, the XML declaration, the root's
  other attributes); every element a table is read from is parsed in full when it is read, and
  refused there.

## Verification

- `tests/test_pmxml.py::test_a_p6_xml_export_is_recognised_and_its_baselines_listed`,
  `::test_the_baseline_read_is_the_one_asked_for_else_the_project_baseline`,
  `::test_an_ambiguous_or_absent_baseline_is_refused_with_the_list`,
  `::test_a_calendar_reads_as_the_xer_writes_it`, `::test_fields_are_converted_to_the_xer_codes`,
  `::test_the_same_baseline_read_from_xml_or_xer_gives_the_same_planned_value`,
  `::test_each_update_is_measured_against_the_baseline_its_file_names_in_the_xml`,
  `::test_a_baseline_read_with_its_index_reads_no_byte_of_another_baseline`,
  `::test_an_export_read_from_the_disk_gives_what_its_bytes_give`,
  `::test_an_export_cut_or_gone_from_the_disk_since_its_index_is_a_xer_error`,
  `::test_a_name_found_only_in_the_xml_baseline_never_reaches_an_anonymized_download`.
- `tests/test_pmxml_scan.py::test_a_file_written_as_p6_writes_one_is_indexed_by_the_search_as_by_the_full_pass`,
  `::test_the_search_gives_up_on_what_it_does_not_read_and_the_file_is_parsed_whole`,
  `::test_a_cdata_section_is_read_as_the_text_it_holds`,
  `::test_on_random_files_the_search_gives_the_index_of_the_full_pass_or_gives_up`,
  `::test_a_file_damaged_inside_an_activity_is_indexed_and_refused_when_its_baseline_is_read`.
- `tests/test_reference_pmxml.py::test_the_xml_gives_the_baseline_the_xer_gives`,
  `::test_an_update_measured_against_the_xml_baseline_reads_as_against_the_xer_baseline` (public
  MPXJ pairs, P6 as oracle; they skip without the fetched reference files, ADR-0014).
- `tests/test_baseline_resolution.py` (the order of the resolution, versions by ObjectId,
  `content_digest`).
- `tests/test_app.py::test_a_baseline_xer_of_the_baselines_subfolder_is_picked_under_the_name_of_an_update`,
  `::test_locked_server_offers_the_p6_xml_files_of_its_folder_as_the_baseline_file`.
- `tests/pmxmlkit.py` builds the synthetic P6 XML exports the tests read; no real export is in the
  repository (ADR-0014).

## References

- `src/xerscope/xer/pmxml.py`: module docstring, `XmlBaseline`, `XmlProject`, `DiskFile`,
  `is_pmxml`, `index_pmxml`, `_index_by_parsing`, `PARSE_CHUNK_BYTES`, `list_baselines`,
  `choose_baseline`, `_document_of`, `read_pmxml_baseline`.
- `src/xerscope/xer/pmxml_scan.py`: module docstring, `scan_export`, `NotPlain`.
- `src/xerscope/xer/__init__.py`: `load_snapshot`, `pmxml_files`.
- `src/xerscope/analysis/baseline_resolution.py`: `resolution`, `resolutions`, `IN_FILE`,
  `IN_EXPORT`, `LOADED_UPDATE`, `SAME_GENERATION`, `UNDECIDED`, `NOT_FOUND`;
  `src/xerscope/analysis/baseline.py:content_digest`.
- `src/xerscope/app/baseline_export.py`, `app/baseline_file.py` (`BASELINES_FOLDER`),
  `app/xml_baselines.py`, `app/baselines.py` (`_resolved_baseline`, `_chosen_baseline`).
- [docs/architecture.md](../architecture.md) §5 "Baseline sources", §7 (`baseline_file.py`,
  `baseline_export.py`, `xml_baselines.py`).
- Related: ADR-0002 (the XER model and load contract), ADR-0014 (no real schedule in the
  repository), ADR-0018 (the baseline each page reads).
