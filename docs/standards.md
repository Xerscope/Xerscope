# Standards in xerscope

Built in: **P6 Check Schedule** (P6 Professional 24), **DCMA DECM v8.0** (the schedule
metrics DCMA applies from FY2026), **DCMA 14-Point** (legacy, still the common screen),
**Integrity** (does the file match a P6-exact recalculation) and **your own standard**.
All are TOML files (`src/xerscope/standards/`) built on one rule library
(`analysis/rules.py`), so they differ only in data: rule, parameters, population, target.

GAO-16-89G and NDIA PASEG v6.0 are out of scope for now (notes at the end).

## Same check, several definitions

| Check | P6 Check Schedule | DCMA 14-Point | DECM v8.0 |
|---|---|---|---|
| Units | hours (352 h = 44 d × 8 h) | working days of each activity's calendar | working days |
| Activities checked | WBS summary and actual-finished removed; LOE removed for constraints, float, durations, BEI | incomplete activities, LOE excluded | incomplete (no actual finish) tasks and milestones; LOE per metric |
| Relationships checked | all except links between two finished activities | links into incomplete work | links into incomplete work |
| Logic | open ends; actual start or start milestone pass the predecessor check, finish milestones the successor check, external links pass | open ends + dangling start/finish; only the project start and finish are exempt | 06A204b: open start = only FF/SF predecessors or none; open finish = only SS/SF successors or none; a milestone only needs one link; started tasks count; earliest baseline start / latest baseline finish exempt |
| Hard constraints | Mandatory Start, Mandatory Finish | MSO, MFO, SNLT, FNLT and mandatory | Mandatory Start, Mandatory Finish (Primavera), target 0 % |
| Lags | links with a positive lag | links with a positive lag | activities with ≥ 1 lagged predecessor, ≤ 10 % |
| Long durations | remaining > 352 h, milestones excluded | original > 44 wd | n/a |
| Out of sequence | n/a | n/a | 06A212a: relationships, actual else forecast dates, X = 0 |
| BEI | activity without a baseline finish = due | activities without a baseline left out | n/a (EVMS cost metrics) |

These differences change results on real files: see `tests/test_rules.py` for one
hand-made schedule per difference.

## P6 Check Schedule (P6 Professional 24: 14 checks)

Order and groups of the P6 Professional 24 User Guide (Check Schedule, page 101393).
Dangling start / dangling finish are not P6 Professional checks (they exist in P6 EPPM),
so they are not in this standard; the `dangling` rule stays available for your own.
Subsets from Oracle's help for each section of the Schedule Check Report (pages
46277–46291). Every percentage = items found / items in the checked subset.

| ID | Group | Check | Subset (Oracle) | Default target here |
|---|---|---|---|---|
| P6-01 | Inflexibility and Inefficiency | Logic | WBS summary, actual finish removed; exemptions above | ≤ 5 % |
| P6-02 | | Hard constraints | WBS, actual finish, LOE removed; start constraints ignored once started | ≤ 5 % |
| P6-03 | | Soft constraints | idem | ≤ 5 % |
| P6-04 | | Large durations (remaining > 352 h) | + milestones removed | ≤ 5 % |
| P6-05 | | Long lags (> 352 h) | links, both-finished removed | ≤ 5 % |
| P6-06 | | Large float (> 352 h) | WBS, actual finish, LOE removed | ≤ 5 % |
| P6-07 | | Relationship types (FS share) | links, both-finished removed | ≥ 90 % |
| P6-08 | | Lags | idem | ≤ 5 % |
| P6-09 | Inaccuracy | Negative lags | idem | ≤ 0 % |
| P6-10 | | Invalid progress dates (forecast before / actual after the data date) | WBS, LOE, finished-before-data-date removed | ≤ 0 % |
| P6-11 | | Resource / cost | WBS, milestones, LOE removed (completed stay in); a role assignment counts | ≤ 0 % |
| P6-12 | Lateness | Late activities (finish variance < 0, working time) | WBS, actual finish, milestones, LOE removed | ≤ 5 % |
| P6-13 | | BEI | completed / due by data date; no baseline finish = due | ≥ 0.95 |
| P6-14 | | Negative float | WBS, actual finish, LOE removed | ≤ 0 % |

**Targets are set in P6's Check Schedule dialog and Oracle does not document defaults.**
Edit `p6.toml` (or a copy) to match your dialog, so pass/fail lines up with P6.

## DCMA DECM v8.0, Guideline 6 (schedule)

EVMS Test Metric Specification v8.0 (21 Aug 2025). Only the automated tests an XER can
answer; DECM's status date is P6's data date.

| ID | Test | X / Y | Target |
|---|---|---|---|
| 06A204b | Dangling logic | open start or finish / incomplete non-LOE tasks and milestones | 0 % |
| 06A205a | Lags | with ≥ 1 lagged predecessor / incomplete tasks and milestones | ≤ 10 % |
| 06A208a | Summary tasks with logic | WBS summary activities with a link | X = 0 |
| 06A209a | Hard constraints | Mandatory Start / Finish / incomplete | 0 % |
| 06A210a | LOE with discrete successors | incomplete LOE driving non-LOE work / incomplete LOE | 0 % |
| 06A211a | High total float | > 44 wd / incomplete non-LOE (DECM samples these for rationale) | info |
| 06A212a | Out of sequence | FS (S.AS\|S.FS) < P.FF, SS (S.AS\|S.FS) < P.FS, FF (S.AF\|S.FF) < P.FF, SF (S.AF\|S.FF) < P.FS | X = 0 |
| 06A401a | Critical path test | longest path, +600 wd moves the finish | pass |
| 06A501a | Missing baseline dates | without baseline start or finish / all (summaries excluded) | ≤ 5 % |
| 06A504a / b | Actual start / finish changed | differs from the previous update / with that actual | ≤ 10 % |
| 06A505a | In progress without actual start | % complete > 0, no actual start / with progress | ≤ 5 % |
| 06A505b | Complete without actual finish | 100 %, no actual finish / at 100 % | ≤ 5 % |
| 06A506a | Actual dates after the status date | / with an actual start | ≤ 5 % |
| 06A506b | Forecast before the status date | incomplete with a forecast before the data date | X = 0 |
| 06A506c | Riding the status date | start within 3 wd of the data date in both of two monthly updates, or remaining duration within ± 2 wd / incomplete | ≤ 1 % |

Not included: 06A301a (vertical traceability), 06I101b (schedule margin), 06I201a
(schedule visibility tasks): they need a summary schedule or your coding convention.

**Status date vs data date.** DECM 06A506b says "on or before the status date": the end
of the reported period. P6's data date is the first instant of remaining work, so a
forecast exactly on it is valid; the equivalent test is "before the data date"
(`include_data_date = false`). Set it to `true` if your organisation reads it literally.

## DCMA 14-Point (legacy)

| # | Metric | Counts | Target |
|---|---|---|---|
| 1 | Logic | open ends incl. dangling start/finish | ≤ 5 % |
| 2 | Leads | negative lags | 0 |
| 3 | Lags | positive lags | ≤ 5 % |
| 4 | Relationship types | FS share | ≥ 90 % |
| 5 | Hard constraints | MSO, MFO, SNLT, FNLT, mandatory | ≤ 5 % |
| 6 | High float | > 44 wd | ≤ 5 % |
| 7 | Negative float | < 0 | 0 |
| 8 | High duration | original > 44 wd | ≤ 5 % |
| 9 | Invalid dates | forecast before / actual after data date | 0 |
| 10 | Resources | duration but no resource or cost | 0 % |
| 11 | Missed tasks | due by the data date (baseline), not finished or finished on a later date | ≤ 5 % |
| 12 | Critical path test | +600 wd on the first open activity of the longest path moves the finish as much | pass |
| 13 | CPLI | (CPL + TF) / CPL, CPL in working hours to the finish | ≥ 0.95 |
| 14 | BEI | completed / due (baseline finish ≤ data date) | ≥ 0.95 |

Calibrated on xerlock's published result for its sample schedule: all twelve stated
values reproduce (`tests/test_reference.py`), as does its critical path test (MEP-020,
+600 wd) and CPL (1080 h).

## Integrity

| ID | Check |
|---|---|
| INT-01 | stored early/late dates and total float = a P6-exact recalculation |
| INT-02 | out-of-sequence progress (info) |
| INT-03 | stored resource-assignment remaining dates = the recalculation |

## Your own standard

```bash
uv run xerscope standards --template my-standard.toml   # every rule, commented
uv run xerscope standards --rules                        # rules and their parameters
uv run xerscope check exports/ --standard my-standard.toml --baseline BL.xer
uv run xerscope app --data exports/ --standards folder-with-my-toml/
```

A wrong rule, parameter, population keyword or target is rejected on load with the exact
name, so a typo cannot silently change a result. `group` (optional) gives a section title.

## Out of scope for now (research notes, Oct 2026)

| Standard | Current version | Note |
|---|---|---|
| DCMA DECM, other guidelines | v8.0 | EVMS cost data an XER does not carry |
| GAO Schedule Assessment Guide | GAO-16-89G, Dec 2015 | ten qualitative best practices |
| NDIA PASEG | v6.0, 30 Sep 2025 | guidance and GASP principles |
| AACE RP 29R-03 | rev. 2011 | window analysis: the base for the changelog and weekly trends, and for TIA later |

## Sources

- [Oracle P6 Professional 24 User Guide: Check Schedule](https://docs.oracle.com/cd/F88968_01/English/User_Guides/p6_pro_user/101393.htm)
- [Oracle P6 Professional 24: Schedule Options, General tab](https://docs.oracle.com/cd/F88968_01/client_help/en_US/general_tab_-_schedule_options_dialog_box.htm)
- [Oracle P6 help: Report tab of the Check Schedule dialog (section index)](https://docs.oracle.com/cd/G18294_01/p6help/en/101231.htm)
- [Oracle P6 help: Logic section](https://docs.oracle.com/cd/G18294_01/p6help/en/46291.htm),
  [Long lags](https://docs.oracle.com/cd/G18294_01/p6help/en/46288.htm),
  [Hard constraints](https://docs.oracle.com/cd/G18294_01/p6help/en/46286.htm),
  [Large durations](https://docs.oracle.com/cd/G18294_01/p6help/en/46282.htm),
  [BEI](https://docs.oracle.com/cd/G18294_01/p6help/en/46277.htm)
- [Oracle P6 help: About activity types](https://docs.oracle.com/cd/G18294_01/p6help/en/43407.htm)
- [Oracle P6 EPPM user guide: early and late dates, resource-dependent activities](https://docs.oracle.com/cd/F37125_01/English/User_Guides/p6_eppm_user/98346.htm)
- [Oracle P6 Professional: Earned Value admin preferences](https://docs.oracle.com/cd/F37128_01/client_help/en_US/earned_value_tab_-_admin_preferences_dialog_box.htm)
- [DECM v8.0 schedule test specifications (SSI index of the DCMA sheets)](https://ssitools.com/helpandsuport/DECM/help/ssi_decm_schedule_tests.htm):
  [06A204b](https://ssitools.com/helpandsuport/DECM/06A204b.pdf),
  [06A205a](https://ssitools.com/helpandsuport/DECM/06A205a.pdf),
  [06A209a](https://ssitools.com/helpandsuport/DECM/06A209a.pdf),
  [06A211a](https://ssitools.com/helpandsuport/DECM/06A211a.pdf),
  [06A212a](https://ssitools.com/helpandsuport/DECM/06A212a.pdf),
  [06A504a](https://ssitools.com/helpandsuport/DECM/06A504a.pdf),
  [06A506b](https://ssitools.com/helpandsuport/DECM/06A506b.pdf),
  [06A506c](https://ssitools.com/helpandsuport/DECM/06A506c.pdf)
- [DCMA EVMS Center](https://www.dcma.mil/HQ/EVMS/)
- [Ten Six: options for scheduling progressed activities in P6](https://tensix.com/options-for-scheduling-progressed-activities-in-p6/)
- [Ten Six: using the P6 Check Schedule tool](https://tensix.com/using-the-p6-check-schedule-tool/)
- [DCMA 14-Point Assessment metric descriptions (Deltek Acumen help)](https://help.deltek.com/Product/Acumen/8.11/GA/DCMA%2014%20Point%20Assessment%20Metric%20Descriptions.html)
- [GAO-16-89G Schedule Assessment Guide](https://www.gao.gov/products/gao-16-89g)
- [NDIA PASEG v6.0](https://www.humphreys-assoc.com/?p=13023)
- [xerlock (reference results)](https://github.com/joaompfp/xerlock)
