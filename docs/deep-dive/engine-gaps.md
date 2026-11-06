# Where the xerscope CPM engine still differs from P6 23.12 on the held-out corpus

Measured 2026-11-06 on branch `claude/wizardly-ptolemy-b4zjg4`, 30 sets (H1–H30) of the pinned
corpus (`tests/reference/data/p6-heldout/validation/held-out`, commit `313701d8`), scored with
`xerscope.verify.p6_corpus.p6_heldout_score` (P6's post-import sizing laid over the cases, as the
test does). 54,726 values, 48,948 identical (89.44 %), 5,778 different. No change to `src/`.
The MPXJ cross-check was not run: a JDK is on the machine but the pinned MPXJ scheduler build
(`tests/reference/mpxj_cpm.py`) was not attempted in this session, so no MPXJ value is quoted here.

Scripts and raw tables are beside this file: `score_all.py` → `scores.csv` (every value with its
shape), `roots.py` → `wrong_roots.csv` (root vs propagated), `blame.py` → `blame.csv` (each wrong
value attributed to the root activities it descends from), `mandatory.py` → `mandatory.csv`,
`project_finish.csv`, `dump.py` (one activity's full context), `gains.csv`.

## 1. Per-set and per-column scores (share identical to P6, %)

ES/EF = early start/finish (remaining dates for work under way), LS/LF = late, TF/FF = total/free
float. Floor = `FLOORS` in `tests/test_p6_heldout.py`. Every set is at or above its floor.

| Set | Values | Floor | Score | ES | EF | LS | LF | TF | FF | Wrong |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 1236 | 1.00 | 1.0000 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0 |
| H2 | 1026 | 0.99 | 0.9981 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 98.8 | 2 |
| H3 | 1518 | 0.99 | 0.9967 | 100.0 | 100.0 | 99.6 | 99.6 | 99.6 | 99.2 | 5 |
| H4 | 1422 | 1.00 | 1.0000 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0 |
| H5 | 1230 | 0.99 | 0.9967 | 99.5 | 99.5 | 100.0 | 100.0 | 99.5 | 99.5 | 4 |
| H6 | 1560 | 0.99 | 0.9987 | 99.6 | 100.0 | 100.0 | 100.0 | 100.0 | 99.6 | 2 |
| H7 | 1452 | 1.00 | 1.0000 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0 |
| H8 | 1572 | 0.99 | 0.9962 | 100.0 | 100.0 | 99.2 | 99.6 | 99.6 | 99.2 | 6 |
| H9 | 1758 | 0.99 | 0.9989 | 100.0 | 100.0 | 99.7 | 100.0 | 99.7 | 100.0 | 2 |
| H10 | 1524 | 0.96 | 0.9705 | 99.2 | 99.2 | 94.9 | 95.3 | 94.9 | 98.8 | 45 |
| H11 | 1440 | 0.99 | 0.9938 | 99.6 | 99.2 | 99.6 | 99.6 | 98.8 | 99.6 | 9 |
| H12 | 1764 | 0.98 | 0.9881 | 99.3 | 99.0 | 99.0 | 98.6 | 98.3 | 98.6 | 21 |
| H13 | 1620 | 0.99 | 0.9907 | 98.9 | 98.5 | 99.6 | 100.0 | 98.5 | 98.9 | 15 |
| H14 | 1266 | 0.95 | 0.9550 | 94.3 | 93.4 | 98.1 | 98.6 | 92.4 | 96.2 | 57 |
| H15 | 1392 | 0.99 | 0.9957 | 100.0 | 100.0 | 98.7 | 99.6 | 99.1 | 100.0 | 6 |
| H16 | 1368 | 0.89 | 0.8991 | 97.4 | 97.8 | 84.2 | 84.2 | 82.5 | 93.4 | 138 |
| H17 | 1272 | 0.95 | 0.9528 | 99.1 | 99.1 | 92.0 | 92.0 | 92.5 | 97.2 | 60 |
| H18 | 1302 | 0.97 | 0.9793 | 100.0 | 100.0 | 94.5 | 96.8 | 96.8 | 99.5 | 27 |
| H19 | 1344 | 0.98 | 0.9821 | 97.8 | 97.8 | 99.1 | 99.6 | 96.4 | 98.7 | 24 |
| H20 | 1242 | 0.94 | 0.9444 | 97.6 | 97.1 | 92.3 | 92.3 | 89.9 | 97.6 | 69 |
| H21 | 1290 | 0.99 | 0.9969 | 100.0 | 99.5 | 100.0 | 100.0 | 100.0 | 98.6 | 4 |
| H22 | 1722 | 0.99 | 0.9942 | 100.0 | 100.0 | 99.0 | 98.6 | 99.3 | 99.7 | 10 |
| H23 | 1854 | 0.76 | 0.7654 | 77.0 | 75.7 | 78.0 | 78.0 | 68.9 | 81.6 | 435 |
| H24 | 1746 | 0.72 | 0.7211 | 73.9 | 73.9 | 71.5 | 72.9 | 61.2 | 79.4 | 487 |
| H25 | 2436 | 0.74 | 0.7455 | 79.6 | 75.6 | 73.9 | 75.9 | 62.8 | 79.6 | 620 |
| H26 | 2496 | 0.78 | 0.7857 | 85.1 | 83.2 | 77.9 | 78.4 | 69.5 | 77.4 | 535 |
| H27 | 3264 | 0.76 | 0.7650 | 81.2 | 80.5 | 75.7 | 77.0 | 65.3 | 79.2 | 767 |
| H28 | 3426 | 0.74 | 0.7452 | 82.3 | 80.9 | 71.8 | 72.2 | 62.3 | 77.6 | 873 |
| H29 | 4104 | 0.76 | 0.7683 | 81.3 | 81.1 | 79.5 | 80.1 | 61.8 | 77.0 | 951 |
| H30 | 4080 | 0.85 | 0.8520 | 89.7 | 88.4 | 86.0 | 87.4 | 75.6 | 84.1 | 604 |
| **all** | 54726 | — | 0.8944 | 92.0 | 91.4 | 89.1 | 89.6 | 84.0 | 90.6 | 5778 |
Per column, all sets: ES 92.0 %, EF 91.4 %, LS 89.1 %, LF 89.6 %, TF 84.0 %, FF 90.6 %.
Task-dependent work (incl. milestones, LOE): 92.0 %; resource-dependent work: 81.3 %
(early 85–88 %, late 79–80 %, TF 70 %). H1–H22 are at 89.9–100 %; H23–H30 (the sets whose
generator draws two constraints per activity, Mandatory dates beside expected finishes, and
larger resource-dependent networks) are at 72–85 % and hold 5,272 of the 5,778 differences (91 %).

## 2. Differences by shape

**Propagation first.** Only 1,539 of the 5,778 differing values (27 %) are *roots*: an early
date whose predecessors all agree with P6, a late date whose successors all agree, a float whose
dates agree. The other 4,239 (73 %) descend from a root through the logic or the project end
(43 of 359 cases have a latest early finish different from P6's, which moves every open end's
late date). Ranking shapes by raw count therefore misleads: the top raw shape, "not started ·
task dependent · finish on or before · pred FS · succ FS" (385 wrong of 1,260), has **zero**
root values; it is always downstream of something else. The tables below use the `--report`
label (status · type · constraint(s) · expected finish · pred links · succ links · lag · option)
and attribute each wrong value to its root(s) (`blame.py`; a value with k roots counts 1/k each).

### 2a. Raw count, `--report` shape (top 12 of 5,778)

| Shape | Values | Wrong | Share | Fields wrong |
|---|---|---|---|---|
| not started · task dependent · finish on or before · pred FS · succ FS | 1,260 | 385 | 31 % | FF 107, TF 92, ES 91, EF 91 (all propagated) |
| not started · resource dependent · pred FS · succ FS | 1,182 | 292 | 25 % | FF 72, TF 69, LS 54, EF 40, LF 32, ES 25 |
| not started · resource dependent · pred FS · succ FS+SS | 708 | 164 | 23 % | TF 57, LF 52, LS 26, EF 17, ES 11 |
| not started · task dependent · pred FS · succ FS | 1,848 | 134 | 7 % | FF 39, TF 27, LS 26, LF 26 |
| not started · resource dependent · mandatory start · expected finish · pred FS · succ FS | 246 | 124 | 50 % | LS 39, LF 39, TF 35, FF 11 |
| not started · finish milestone · pred FF+FS · succ none · lag | 1,560 | 94 | 6 % | ES/EF 25 each, LS/LF 13 each |
| not started · resource dependent · pred FS · succ FS+SS · lag | 264 | 88 | 33 % | LS 25, LF 22, TF 18 |
| not started · resource dependent · as late as possible · pred FS · succ FS+SS | 390 | 86 | 22 % | TF 26, ES/EF 18 each |
| not started · task dependent · as late as possible · pred FS · succ none | 420 | 77 | 18 % | ES/EF 21 each, TF 13 |
| not started · resource dependent · as late as possible · pred FS · succ FS | 396 | 76 | 19 % | TF 24, ES/EF 12 each, FF 12 |
| not started · task dependent · start on or after · pred FS · succ FS | 894 | 75 | 8 % | FF 21, LS/LF 18 each, TF 18 |
| not started · resource dependent · pred FF+FS · succ FS | 288 | 73 | 25 % | TF 16, ES 15, EF 13, FF 13 |

### 2b. Root shapes, coarse label (status · type · constraints · expected finish), with every value attributed to them

| Rank | Root shape | Root activities | Own wrong values | Attributed wrong values (incl. propagated) | Share of all 5,778 |
|---|---|---|---|---|---|
| 1 | not started · resource dependent · no constraint | 165 | 397 | 895 | 15.5 % |
| 2 | not started · resource dependent · mandatory finish · expected finish | 30 | 107 | 546 | 9.5 % |
| 3 | not started · resource dependent · as late as possible | 76 | 217 | 349 | 6.0 % |
| 4 | not started · task dependent · start on or after + mandatory finish (slot 2) | 21 | 76 | 340 | 5.9 % |
| 5 | not started · resource dependent · mandatory finish (no expected finish) | 18 | 46 | 244 | 4.2 % |
| 6 | not started · task dependent · mandatory start + mandatory finish (slot 2) | 20 | 64 | 203 | 3.5 % |
| 7 | not started · task dependent · mandatory finish · expected finish | 11 | 38 | 192 | 3.3 % |
| 8 | not started · finish milestone · mandatory finish · expected finish | 13 | 59 | 178 | 3.1 % |
| 9 | not started · task dependent · no constraint | 61 | 152 | 173 | 3.0 % |
| 10 | not started · task dependent · finish on or before + mandatory finish (slot 2) | 9 | 33 | 164 | 2.8 % |
| 11 | not started · resource dependent · mandatory start · expected finish | 41 | 121 | 163 | 2.8 % |
| 12 | in progress · task dependent · no constraint | 36 | 110 | 154 | 2.7 % |
| 13 | in progress · resource dependent · no constraint | 46 | 97 | 151 | 2.6 % |
| 14 | not started · task dependent · mandatory start + start on or after (slot 2) | 4 | 15 | 130 | 2.2 % |
| 15 | not started · finish milestone · finish on · expected finish | 12 | 36 | 130 | 2.2 % |
| 16 | LOE (not started + in progress) · no constraint | 36 | 64 | 204 | 3.5 % |
| 17 | start milestone · expected finish (none / mandatory start / start on or after) | 19 | 57 | 214 | 3.7 % |

Grouped into families (same P6 rule at play):

| Family | Attributed wrong values | Share | Own wrong values (lower bound) |
|---|---|---|---|
| **A. Mandatory Start / Finish handled as a pin in every case** (slot 2, with an expected finish, on work under way, on resource-dependent work) | 2,920 | 50.5 % | 1,519 (663 unfinished activities carry a mandatory date; 2.3 wrong values each) |
| **B. Resource-dependent work without a constraint** (placement, late bounds, assignments without work) | 1,046 | 18.1 % | 494 |
| **C. Milestones and tasks with an expected finish, no mandatory date** | 552 | 9.6 % | 201 |
| **D. Resource-dependent As Late As Possible work** | 444 | 7.7 % | 225 |
| E. Task-dependent / LOE work without a constraint (open ends behind a different project finish, free float, LOE late dates) | 530 | 9.2 % | 326 (83 of the 98 open-end root values sit in the 43 cases where P6's project finish differs, i.e. are themselves downstream of A, B or D) |
| other | ~290 | 5 % | |

## 3. Diagnosis of the top shapes (two activities each; P6 vs xerscope, context, likely rule)

All dates are P6's stored values from `p6-results.csv`; "xs" is xerscope. Links read "type lag".
Full context (calendars, assignments, every neighbour's four dates) is in `dump_mandatory.txt`,
`dump_other.txt`, `dump_inprog.txt`.

### A. Mandatory dates (rows 2, 4, 5, 6, 7, 8, 10, 11, 14 of table 2b): 50 % of all differences

What the engine does (`cpm.py forward()`, `constraints()`, `forward_constraints()`, `backward`):
`constraints()` returns both slots; `forward_constraints` returns the **last** mandatory date it
meets as `pinned`; the early finish/start is pinned to it (`pinned[0] == "finish"` branch) unless
the activity is task-dependent *and* its expected finish already applied (`duration_override`);
the backward pass pins the late dates to any mandatory date, started or not. P6 23.12 in the
corpus pins far less often:

| Group (unfinished, mandatory date present) | n | P6 early date at the mandatory date | P6 late date at the mandatory date | xs agrees early | xs agrees late | xs wrong values |
|---|---|---|---|---|---|---|
| not started · task · MF slot 1 · no expected finish | 58 | 91 % | 76 % | 100 % | 98 % | 25 |
| not started · task · MS slot 1 · no expected finish | 95 | 75 % | 64 % | 77 % | 73 % | 191 |
| not started · task · MF slot 1 · **expected finish in force** | 74 | 22 % | 20 % | 73 % | 64 % | 118 |
| not started · finish milestone · MF slot 1 · expected finish | 15 | 20 % | 27 % | 13 % | 7 % | 69 |
| not started · rsrc · MF slot 1 · expected finish | 44 | 32 % | 32 % | 52 % | 55 % | 93 |
| not started · rsrc · MS slot 1 · expected finish | 48 | 29 % | 42 % | 100 % | 17 % | 118 |
| not started · task · **MF in slot 2** (behind SNET, MS, FNLT, ...) | 79 | 51 % | 49 % | 48 % | 49 % | 262 |
| not started · rsrc · MF in slot 2 | 19 | 26 % | 68 % | 11 % | 89 % | 70 |
| not started · rsrc · MF slot 1 · no expected finish | 56 | 64 % | 80 % | 32 % | 93 % | 116 |
| not started · rsrc · MS slot 1 · no expected finish | 81 | 63 % | 48 % | 91 % | 32 % | 241 |
| **in progress** · any · MF either slot | 73 | 25–32 % | 3–12 % | 97–100 % | **0 %** | 236 |
| **in progress** · any · MS either slot | 20 | 0 % | **0 %** | 100 % | **0 %** | 62 |

The two shapes with the largest payoff, with their witnesses:

**A1. Mandatory Finish in slot 1 with an expected finish in force (rows 2, 7, 8: 916 attributed values).**

- *H24-03 A1170* (H24, progress override, FT_FF, lag on project default calendar, Use Expected
  Finish on). Resource dependent, 8.5 h remaining, one assignment 32 units at 4/h, Mandatory
  Finish Mon 24 Aug 12:00, expected finish Wed 19 Aug 12:00. Predecessors: A1090 FS +16 h
  (P6 EF Tue 1 Sep 13:30, xs agrees), A1100 FS −4 h (in progress, agrees). Successors A1180,
  A1250, A1350 (FS 0). **P6:** ES Thu 3 Sep 09:00, EF Fri 4 Sep 09:00 — from the logic
  (A1090 finish + 16 h on the resource calendar), the Mandatory Finish and the expected finish
  both ignored; LS Tue 11 Aug 09:00, LF Wed 12 Aug 09:00 from A1180's late start; TF −138 h.
  **xs:** ES 20 Aug 14:00, EF 24 Aug 12:00 pinned to the MF in both passes, TF 0. All 3
  successors then wrong (67 attributed values in this case alone).
- *H27-08 A1150* (H27, progress override, lag on predecessor calendar). Task dependent, 16 h,
  Mandatory Finish Sat 11 Apr 18:00, expected finish Thu 2 Apr 18:00 (before the data date's
  logic). Predecessor A1130 FF +24 h (rsrc, P6 EF Wed 8 Apr 08:00, agrees); successors A1200
  FS, A1210 FF. **P6:** EF Fri 10 Apr 08:00 = A1130 finish + 24 h on the predecessor calendar,
  ES Wed 8 Apr 16:00 = EF − 16 h; LS/LF 18–20 Mar from A1200's late start; TF −228 h. **xs:**
  pinned to the MF (10 Apr 14:00 → 11 Apr 18:00), TF 0, FF 2 h (P6 0).
- Same on finish milestones: *H26-08 A1390* (MF 23 Sep 17:30, expected finish 17 Sep 17:30 =
  predecessor finish): P6 sits at 17 Sep 17:30, late 17 Sep 09:00 from its successor; xs at the
  MF in both passes. *H28-11 A1330* (MF 5 Dec 16:00, expected finish 2 Dec 16:00 before the
  predecessor's finish 5 Dec 14:00): P6 sits at the predecessor's finish, late from the successor.

  Likely P6 rule: **an expected finish in force (option on, date set) on unstarted work takes the
  Mandatory Finish off, in both passes; the activity follows its logic / expected finish and the
  mandatory date caps nothing it does not already cap.** The corpus authors name it "XP: an
  expected finish in force on work not yet started lifts the Mandatory Finish pin. The date caps
  the late finish, as a Finish On does" (H23 PROTOCOL.md; "XP decided 11 activities, all
  matching", H23 RESULT.md). docs/cpm.md already has the late half of it for task-dependent work
  ("with an expected finish earlier than a Mandatory Finish the date no longer pins: the
  successors drive, capped by the expected finish (H23-03 A1210) or, on resource-dependent work,
  by the mandatory date (H25-05 A1150)"), and PINNED holds H22-06 A1120, H23-03 A1210, H23-07
  A1110, H25-05 A1150 for it. What is missing: the early side (the pin is kept whenever the
  expected finish did not apply, i.e. on every resource-dependent activity, every milestone, and
  every task whose expected finish fell before its early start or behind an FF/SF bound).
  Note the H25-05 A1150 cap "by the mandatory date on resource-dependent work" is a 3-case
  observation that this reading would have to re-test.

**A2. Mandatory date in the second slot (rows 4, 6, 10, 14: 837 attributed values).**

- *H29-12 A1110* (H29, retained logic, lag on successor calendar, SS lag from actual start).
  Task, 8 h, slot 1 Start On or After Tue 13 Oct 00:00, slot 2 Mandatory Finish Sun 18 Oct 00:00.
  Predecessors A1050 SS +16 h, A1070 FS +16 h (P6 EF Wed 21 Oct 16:00), A1090 FS +40 h.
  **P6:** ES Fri 23 Oct 08:00, EF 16:00 — from the logic (A1070 + 16 h), the slot-2 MF only a
  floor; LS Thu 8 Oct 06:00, LF 14:00 from the successors (below the MF, so the cap does not
  bind); TF −362 h. **xs:** pinned to the MF in both passes (ES 17 Oct 16:00, EF 18 Oct 00:00),
  TF 0; 7 successors wrong (66 attributed values).
- *H26-08 A1280* (H26, progress override). Task, 16 h, slot 1 **Mandatory Start** Mon 5 Oct
  07:00, slot 2 Mandatory Finish Thu 1 Oct 17:30 (earlier than the start!). **P6:** ES = the
  Mandatory Start 5 Oct 07:00, EF 6 Oct 13:30 = ES + 16 h; LF = 1 Oct 17:30 (the slot-2 date as
  a cap), LS = LF − 16 h; TF −16 h. **xs:** `pinned` ends on the last mandatory date met (the
  slot-2 MF) and places the early dates back from it (30 Sep 11:00 → 1 Oct 17:30); late dates
  agree by coincidence. Same in H26-05 A1380 (MS 7 Sep 07:00 / MF 4 Sep 17:00) and H28-07 A1210
  (SNET + MF slot 2: P6 ES from the logic, LF = the MF as a cap, TF −17 h).

  Likely P6 rule: **only the primary constraint pins; a mandatory date in the second slot is a
  Start/Finish On or After forward and a Start/Finish On or Before backward.** Corpus names:
  "PC: only the primary constraint pins. A second constraint caps the late dates, a Mandatory
  Start or Mandatory Finish in the second slot as a Start On or Before or a Finish On or Before
  does" (H23) and "SL: ... A Mandatory Start in the second slot is a Start On or After forward, a
  Mandatory Finish a Finish On or After; on the late side each caps" (H24). docs/cpm.md knows
  one corner ("a second constraint of the same end that is tighter still holds (H23-08 A1220)",
  PINNED) and the backlog says of the family "the deciding factor is not found"; the slot is the
  deciding factor in 79 + 19 + 6 activities here.

**A3. Mandatory dates on work under way (236 + 62 own wrong values, late dates 0 % right).**
*H17-05 A1210* (in progress, remaining 3 h, MF Mon 8 Jun 16:00 in the past): P6 LS 29 Jun 14:00,
LF 30 Jun 09:00 from its successors, TF +78 h; xs pins LF to the MF, TF −76.5 h. *H28-05 A1390*
(in progress, MS 29 Aug 06:00 = its actual start, slot 2 FNLT): P6 LS 25 Sep 13:00 / LF 26 Sep
17:00 from the finish milestone after it, TF = FF = 281 h; xs pins the late start to the MS,
TF −50 h. Likely rule: **a mandatory date on started work pins nothing in the backward pass**
(P6 late date at the mandatory date: 0 of 20 MS, 3–12 % of 73 MF, those few being coincidences
with the successors). `forward_constraints` already skips constraints of started work forward
("Work under way keeps its actual start, so its constraints are not applied here"); the backward
pass does not. The corpus' H28 "UM" rule covers the two-constraint case of it.

**A4. Mandatory dates on resource-dependent work without an expected finish (rows 5, and the
MS part of 11: ~400 attributed).** *H25-05 A1240* (rsrc, 32 h on its calendar, one assignment
120 units at 8/h on another calendar, MF Sun 29 Nov 00:00): P6 ES Fri 27 Nov 16:00 = the start
placed back from the MF by the remaining duration *on the activity calendar* (xs agrees), then the
resource runs forward from that start on its own calendar to EF Tue 1 Dec 15:00 — the finish is
**not** held at the MF; late dates pinned (LF Fri 27 Nov 17:00, agree); TF −94 h, FF 0 (xs 31 h).
*H28-12 A1090* (rsrc, 34.5 h, two resources, MF Thu 21 May 00:00): same ES (agrees), P6 EF Mon
25 May 08:30 from the resources, late dates from the successors (LF 11 May 17:30 < MF), TF −327 h.
Rule as the corpus states it for the start side ("MO: a Mandatory Start on resource dependent
work with no expected finish in force pins the span, on the activity calendar, of the work placed
forward from it on its resources' own calendars, not the stored remaining duration", H30): the
mandatory date fixes one end on the activity calendar and the assignments size the other.
cpm.md's "Resource dependent" paragraph has no mandatory case. The late side of MS on rsrc
work (P6 LS at the MS 48 %, xs 32 % right: H25-03 A1300, H26-01 A1230 — P6 LF = the successor's
late start, below the pin) is the backlog's open "H25-03 A1180 against H10-05 A1180" item.

### B. Resource-dependent work without a constraint (row 1, 13: 1,046 attributed, 18 %)

- *H16-10 A1290* (rsrc, 7 h, resource R2 24 units at 3.69/h on a Mon–Fri 08:00 calendar,
  activity calendar opens 07:00). P6 ES Mon 7 Sep **08:00** (the resource's first working
  minute), xs 07:00 (the activity calendar's opening); EF agrees (15:30). P6's late dates (LS
  2 Sep 09:30, LF 17:00, TF −18.5 h) come from the finish milestone A1300 after it, which P6
  places at Mon 7 Sep **07:00** — *before* A1290's own early finish, so P6 drives the successor
  from a "first placement" of A1290 that it does not display. The corpus' own H23 RESULT.md
  describes exactly this on H23-12 A1230 ("the engine also keeps a first placement ... and
  drives A1230's successors from it. Where P6 keeps such a first placement, as for H20-03 A1060,
  whose resource also first works on a day its calendar has off, it drives the successors from it
  too"). 79.5 attributed values in this one case; H16's whole gap (10.1 points) is this activity.
- *H14-02 A1180* (rsrc, 10 h, assignments R1 0 units at 1/h, R3 4 units at 0.47/h):
  P6 ES Mon 19 Oct 11:00 — one hour *before* its FS predecessor A1170's early finish 12:00
  (agreed); xs 12:30. The backlog names its neighbour ("H14-02 A1220 wants its FF predecessor
  one hour earlier than displayed") and the H25 rule "QS: work a finish-to-finish or
  start-to-finish requirement places starts where its resource first works at or after the
  activity calendar's opening". Late dates agree.
- *H25-01 A1500* (late side): three assignments, two with 0 units; P6 LS 16 Nov 09:00, xs 10:00
  — the corpus' "ZL / ZR" rules on assignments with no work placed back from the late finish.

  Classification: **documented open convention** — cpm.md "Conventions no reference file
  settles: Resource-dependent activity ... The corpus agrees with 79 % of the values; this is the
  engine's largest open area", and the backlog's first item. Many distinct sub-rules (the corpus
  authors needed QS, ZL, ZR, ZF, BM, ZQ, ZU, ZW, RU over H23–H30), each worth 20–80 values; no
  single experiment settles the family.

### C. Milestones with an expected finish, no mandatory date (rows 15, 17: 552 attributed, 9.6 %)

154 unstarted milestones carry an expected finish under "Use Expected Finish Dates". Where the
expected finish is later than the predecessors' finish, P6 sits the milestone **at the expected
finish** (finish milestones: 8/8 without constraint, 12/13 Finish On, 6/7 Finish On or After,
3/3 Mandatory Finish; start milestones: at the expected finish written as a start, i.e. the next
period start: 9/9 without constraint), and xerscope agrees on 0 % of them, because `forward()`
calls `expected_finish()` only for `activity_kind == "task"`. Where the expected finish is
earlier than the logic P6 ignores it (xs 76–80 % right; the misses are downstream).

- *H23-09 A1200* (finish milestone, Finish On Sat 9 Jan 18:00, expected finish Sun 3 Jan 18:00,
  predecessor A1080 EF Fri 1 Jan 11:00): P6 ES = EF = 3 Jan 18:00; late 4 Jan 14:00 from the
  successor; TF +8 h. xs: 9 Jan 18:00 (the Finish On as a floor), TF −64 h; the successor A1210
  then starts 6 days late. Corpus rule "XC on finish milestones: a finish milestone with an
  expected finish drops the early side of Finish On or After, Finish On and Mandatory Finish, and
  sits at its expected finish" (H23, "8 decided, all matching").
- *H26-11 A1370* (start milestone, no constraint, predecessor A1170 EF Thu 4 Mar 12:00):
  P6 ES = EF = Mon 8 Mar 07:00 (the expected finish, written as a task start, the next period
  start); xs 4 Mar 12:30 (predecessor + next working minute). Late dates agree. The corpus lists
  "Start milestone with an expected finish: 24 of 24" in H28.

  Classification: **new** (neither cpm.md nor the backlog names milestones with an expected
  finish; cpm.md's expected-finish rules are stated for tasks).

### D. Resource-dependent As Late As Possible work (row 3: 444 attributed, 7.7 %)

- *H28-05 A1420* (rsrc ALAP, 15 h, one resource 16 units at 1.23/h, successors A1430 SS 0 and
  A1170 FS 0): P6 ES Fri 11 Sep 12:45, EF Mon 14 Sep 09:45, LS 24 Sep 11:00; xs ES 10 Sep 14:45,
  EF 12 Sep 11:45, LS 28 Sep 11:00. P6's SS successor A1430 starts 10 Sep 14:45 — a day before
  A1420's displayed start, so P6 again drives from a placement it does not display, and the
  project finishes 26 Sep 17:00 (xs 29 Sep).
- *H28-12 A1080* (rsrc ALAP, 0 h remaining, assignment 0 units): P6 ES = EF Mon 25 May 08:00
  (its SS successor's bound carried to the resource's next opening), xs 20 May 16:00; FF 0 (xs 8).

  Corpus rules "AR / AW: As Late As Possible resource dependent work under a start-to-start or
  start-to-finish bound is placed two ways and the later holds ..." (H28, H29) and "AZ: such work
  with no work left sits at its resources' next opening at or after the bound". Classification:
  **new** (cpm.md's ALAP paragraph is for task-dependent work; the backlog does not name it).
  P6's own behaviour changed reading between H28 and H29 in the corpus authors' hands: not a
  first experiment.

### E. Task-dependent / LOE work without a constraint (rows 9, 12, 16: 530 attributed, 9.2 %)

- *H23-02 A1380* (task, open end, no constraint): P6 LF Wed 17 Mar 15:00, xs 09:00 = xs's
  project finish; TF/FF 28 vs 23 h. P6's latest early finish in this case is later than xs's
  (one of the 43 cases where the project finish differs because of a resource-dependent or
  mandatory root elsewhere): the "root" is the project end, not a float rule. 83 of the 98
  open-end root values are of this kind.
- *H20-12 A1220* (task, FS −4 h lead from a resource-dependent predecessor whose EF agrees):
  P6 ES 2 h earlier than finish − lead — the backlog's "H10-10 A1140 a lead four days earlier"
  (what a successor sees of a resource-dependent predecessor), family B in disguise.
- The genuinely own cases are the free float of unstarted/started task work with no constraint
  (51 + 25 root values, e.g. H23-05 A1280), the backlog's "free float of started work under
  Progress Override, with counter-examples" item, and LOE late dates (cpm.md "LOE late start
  behind a finished task/SS predecessor", observed conventions). Classification: **backlog /
  documented**, small.

## 4. Classification summary

| Shape / family | Status | Where named |
|---|---|---|
| A1 MF + expected finish, early side on rsrc / milestones / tasks | **partly documented, partly new**: late half in cpm.md + PINNED (H22-06, H23-03, H23-07, H25-05); early half new | backlog "Rules observed, not explained" (3-case H25-05 note), corpus XP |
| A2 mandatory date in slot 2 | **backlog names the symptom** ("Mandatory dates and the late dates ... deciding factor not found"); the slot as the factor is new | cpm.md "a second constraint ... tighter ... still holds (H23-08 A1220)", corpus PC/SL |
| A3 mandatory date on work under way, late side | **new** | corpus UM (partial) |
| A4 mandatory date on rsrc work: span sized by the resources, late of MS | **backlog** (H25-03 vs H10-05) | corpus MR/MO |
| B rsrc placement, no constraint | **documented open convention** | cpm.md "Conventions no reference file settles", backlog item 1 |
| C milestones with an expected finish | **new** | corpus XC, H28 "start milestone with an expected finish" |
| D rsrc ALAP | **new** | corpus AR/AW/AZ/AG |
| E open ends / free float / LOE | documented (project-end propagation of A/B/D; backlog free-float item; cpm.md LOE conventions) | |

## 5. Estimated gain per set (points of the set's score, out of 100)

"own" counts only the wrong values on the root activities themselves (a lower bound, reached as
soon as the activity's own dates are right); "attributed" adds every value that descends from
them (an upper bound, reached only if the propagation is also right, which for family A it
largely is: the neighbours are ordinary tasks). Family A "clear rules" = slot 2, MF with an
expected finish, and started work (A1–A3), where P6's behaviour is ≥ 88 % consistent in the
corpus; the rest of A (A4, MS on rsrc work) is less settled.

| Set | Score | Floor | A own (all mandatory) | A own (clear rules) | A attributed | B rsrc own | B rsrc attributed | C milestones+expf own | C attributed | D rsrc ALAP attributed |
|---|---|---|---|---|---|---|---|---|---|---|
| H2 | 99.8 | 99 | +0.2 | +0.0 | +0.2 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 |
| H3 | 99.7 | 99 | +0.3 | +0.2 | +0.3 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 |
| H5 | 99.7 | 99 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 |
| H6 | 99.9 | 99 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 |
| H8 | 99.6 | 99 | +0.3 | +0.2 | +0.3 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 |
| H9 | 99.9 | 99 | +0.0 | +0.0 | +0.0 | +0.1 | +0.1 | +0.0 | +0.0 | +0.0 |
| H10 | 97.0 | 96 | +0.0 | +0.0 | +0.0 | +0.3 | +0.3 | +0.0 | +0.0 | +0.0 |
| H11 | 99.4 | 99 | +0.0 | +0.0 | +0.0 | +0.1 | +0.1 | +0.0 | +0.0 | +0.0 |
| H12 | 98.8 | 98 | +0.2 | +0.0 | +0.6 | +0.2 | +0.2 | +0.1 | +0.1 | +0.0 |
| H13 | 99.1 | 99 | +0.0 | +0.0 | +0.0 | +0.1 | +0.1 | +0.0 | +0.0 | +0.0 |
| H14 | 95.5 | 95 | +0.6 | +0.5 | +0.6 | +0.2 | +2.6 | +0.0 | +0.0 | +0.0 |
| H15 | 99.6 | 99 | +0.0 | +0.0 | +0.0 | +0.2 | +0.2 | +0.1 | +0.1 | +0.0 |
| H16 | 89.9 | 89 | +0.5 | +0.2 | +0.5 | +0.9 | +6.4 | +0.1 | +0.1 | +0.0 |
| H17 | 95.3 | 95 | +0.6 | +0.6 | +0.6 | +0.1 | +0.1 | +0.0 | +0.0 | +0.0 |
| H18 | 97.9 | 97 | +0.8 | +0.7 | +0.8 | +0.5 | +0.8 | +0.0 | +0.0 | +0.0 |
| H19 | 98.2 | 98 | +0.1 | +0.0 | +0.1 | +0.6 | +0.9 | +0.0 | +0.0 | +0.0 |
| H20 | 94.4 | 94 | +0.1 | +0.0 | +0.1 | +0.6 | +4.6 | +0.0 | +0.0 | +0.0 |
| H21 | 99.7 | 99 | +0.2 | +0.0 | +0.2 | +0.1 | +0.1 | +0.1 | +0.1 | +0.0 |
| H22 | 99.4 | 99 | +0.1 | +0.0 | +0.1 | +0.2 | +0.3 | +0.0 | +0.0 | +0.0 |
| H23 | 76.5 | 76 | +5.2 | +3.3 | +12.8 | +0.3 | +0.8 | +1.0 | +2.1 | +0.4 |
| H24 | 72.1 | 72 | +8.6 | +6.2 | +17.2 | +0.2 | +1.0 | +1.6 | +5.1 | +1.3 |
| H25 | 74.6 | 74 | +7.3 | +3.5 | +13.0 | +2.8 | +6.1 | +0.5 | +0.9 | +1.3 |
| H26 | 78.6 | 78 | +4.7 | +1.8 | +14.7 | +1.7 | +2.8 | +0.6 | +1.1 | +0.5 |
| H27 | 76.5 | 76 | +5.0 | +4.0 | +11.6 | +2.2 | +4.2 | +1.4 | +5.2 | +0.5 |
| H28 | 74.5 | 74 | +6.3 | +4.0 | +12.2 | +1.9 | +4.3 | +1.0 | +4.3 | +4.2 |
| H29 | 76.8 | 76 | +7.0 | +4.5 | +12.4 | +2.3 | +4.4 | +0.8 | +1.8 | +2.8 |
| H30 | 85.2 | 85 | +6.5 | +3.0 | +8.2 | +2.1 | +2.6 | +0.3 | +0.7 | +2.3 |
Corpus-wide (54,726 values, now 89.44 %): A own +2.8 (clear rules +1.7), A attributed +5.3;
B own +0.9, attributed +1.9; C own +0.4, attributed +1.1; D attributed +0.8. Family A alone
would lift H23–H30 by 5–9 points on own values and 8–17 points attributed (H24: 72.1 → 80.7 /
89.3); H1–H22 move by ≤ 0.8 points (they carry few mandatory dates; H16's and H20's gaps are
family B, one activity each). FLOORS H1–H22 would stay where they are (the test rounds down to
0.01); H23–H30 floors could rise from 0.72–0.85 to roughly 0.78–0.90 (own) or 0.84–0.93
(attributed) after A, and by a further 1–6 points after B.

## 6. Proposed experiments (no change to `src/`)

### Experiment 1 — family A: "a mandatory date pins only when primary, unstarted and without an expected finish in force"

Hypothesis (one rule, four consequences, each testable alone):
1. Slot 2: a Mandatory Finish/Start in `cstr_type2` is a Finish/Start On or After forward and a
   Finish/Start On or Before backward (never a pin). The primary constraint keeps its full effect.
2. Expected finish in force (`sched_use_expect_end_flag` ≠ N, `expect_end_date` set) on
   unstarted work: a primary Mandatory Finish pins neither pass; the early dates come from the
   logic / expected-finish rules already in `expected_finish()` (also for milestones and
   resource-dependent work), the late dates from the successors, capped by the mandatory date.
3. Work under way: a mandatory date (either slot) bounds no late date; successors drive.
4. Resource-dependent, unstarted, primary Mandatory Finish, no expected finish: the start is
   placed back from the date by the stored remaining duration on the activity calendar (as now),
   the finish is the latest driving assignment run forward from that start on its resource
   calendar (not the date); the late dates stay at the date.

Hand-made xerkit schedule (`tests/xerkit.py`, `xer_text`/`snap`, data date `DD`, calendar C8),
one activity per consequence, each with an FS predecessor `P` (8 h, unstarted) and an FS
successor `S` (8 h) so both passes are observable:
- `todo("MF2", cstr_type="CS_MSOA", cstr_date=<DD+2d>, cstr_type2="CS_MANDFIN", cstr_date2=<DD+1d 17:00>, **hours(16))`
  — expected: ES = max(P finish, DD+2d), EF = ES+16 h (not the MF); LF = min(S late start, MF), TF < 0.
- `todo("MS1MF2", cstr_type="CS_MANDSTART", cstr_date=<DD+5d 08:00>, cstr_type2="CS_MANDFIN", cstr_date2=<DD+3d 17:00>, **hours(16))`
  — expected: ES = the MS, EF = ES+16 h; LF = the MF, LS = LF−16 h, TF −16 h (H26-08 A1280 shape).
- `todo("MFX", cstr_type="CS_MANDFIN", cstr_date=<DD+10d 17:00>, expect_end_date=<DD+4d 17:00>, **hours(16))`
  with `sched={"sched_use_expect_end_flag": "Y"}` — expected: EF = expected finish (or P finish
  if later), LS/LF from S, not the MF; a sibling `MFX_ms` with `**FM` (finish milestone) sits at
  the expected finish; a sibling with `task_type="TT_Rsrc"` and one `assign` row follows its logic.
- `active("MFA", cstr_type="CS_MANDFIN", cstr_date=<DD-2d 17:00>, remain_drtn_hr_cnt="8")`
  — expected: LF = S late start − 0 (not the MF), TF ≥ 0; same with `CS_MANDSTART`.
- `todo("MFR", task_type="TT_Rsrc", cstr_type="CS_MANDFIN", cstr_date=<DD+6d 00:00>, **hours(32))`
  with one assignment on a resource calendar of fewer hours (e.g. 4 h/day) — expected: ES = MF −
  32 h on C8, EF = ES + units/rate on the resource calendar (> MF), LF = MF, FF 0.
Each expected value is the P6 behaviour read off the corpus witnesses below (write the hand
calculation in the test; the current engine fails each of the five).

Corpus activities that confirm or refute each consequence (PINNED candidates):
1. slot 2: H29-12 A1110, H28-07 A1210 (SNET+MF), H26-08 A1280, H26-05 A1380, H23-04 A1140,
   H23-07 A1120 (MS+MF), H27-11 A1060, H28-11 A1160 (FNLT+MF); counter-checks already PINNED:
   H23-08 A1220 (tighter FNLT in slot 1 still caps).
2. expected finish: H24-03 A1170, H27-07 A1210 (rsrc), H27-08 A1150, H25-02 A1240 (task),
   H26-08 A1390, H28-11 A1330 (finish milestones); must keep H22-06 A1120, H23-03 A1210,
   H23-07 A1110, H25-05 A1150 (PINNED), and the 265 "no free float where the expected finish
   applies" values.
3. started work: H17-05 A1210, H28-05 A1390, H27-07 A1550, H29-01 A1590; must keep H3-04
   A1100 / H2-06 A1130 (unstarted, mandatory date before the data date, PINNED).
4. rsrc MF: H25-05 A1240, H28-12 A1090, H29-02 A1170, H23-08 A1230; late side H25-03 A1300,
   H26-01 A1230 (MS, open).
Expected floor gain if 1–3 hold: own +1.7 points corpus-wide, H23–H30 +1.8 to +6.2 each
(table above, "A own (clear rules)"); with 4 and the propagation, up to the "A attributed"
column (+8 to +17 on H23–H30). A gain on these shapes must not cost the 25 + 191 values of
unconstrained primary mandatory dates on tasks that agree today (table in 3.A, rows 1–2).

### Experiment 2 — family C: "a milestone with an expected finish in force sits at it"

Hypothesis: for an unstarted start or finish milestone with `expect_end_date` under "Use Expected
Finish Dates", the early date is max(logic bound, expected finish); the early side of a Finish
On / Finish On or After / Mandatory Finish is dropped (their late side stays a cap); a start
milestone writes the instant as a task start (next period start), a finish milestone as a finish.
Late dates are untouched (they already agree: H23-09 A1200, H26-11 A1370).

xerkit schedule: `P` (8 h) FS→ `FM1` (`**FM`, `expect_end_date=<DD+5d 17:00>`) FS→ `S`;
`P` FS→ `FM2` (`**FM`, `cstr_type="CS_MEO"`, `cstr_date=<DD+9d 17:00>`, `expect_end_date=<DD+5d 17:00>`);
`P` FS→ `SM1` (`**SM`, `expect_end_date=<DD+5d 17:00>`), with `sched={"sched_use_expect_end_flag": "Y"}`.
Expected: FM1 = FM2 = DD+5d 17:00 (FM2's Finish On is not a floor), SM1 = DD+6d 08:00, S after
them; a fourth milestone with the expected finish earlier than P's finish stays at P's finish.
Corpus witnesses: H23-09 A1200, H26-08 A1390, H28-11 A1330 (finish), H26-11 A1370, H27 / H28 /
H29 start milestones in shapes "start milestone · expected finish · pred FS · succ FS" (0 of 9
unconstrained ones agree today, 29 of 42 with Finish On / On or After / MF). Expected gain: own
+0.4 corpus-wide (H24 +1.6, H27 +1.4), attributed up to +1.1 (H24 +5.1, H27 +5.3, H28 +4.3).
Smaller than A but a one-function change (`forward()` calls `expected_finish()` only for
`activity_kind == "task"`), and it shares A1's witnesses on finish milestones.

### Not recommended as a first experiment
Family B (resource-dependent placement) is the largest family after A but P6's rule there is a
hidden "first placement" the corpus authors needed nine sub-rules for; family D (rsrc ALAP)
changed reading between H28 and H29 in their hands. Both need a P6 export of a hand-made file to
settle, not a corpus fit.
