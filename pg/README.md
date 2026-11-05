# PitchGrid benchmark set and "manufacturable" judge (pg-hw #913)

Fork of Koppar-AI/autorouter-bench (MIT, KiCad 10 referee) used as the evaluation harness of the
PitchGrid PCB auto-layout stack (pitchgrid-io/pg-hw RESEARCH/2026-11-05-pcb-autolayout-stack-plan.md).

```sh
export KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
export BOARD_SET=pg BENCH_WORK=<work dir>
python3 scripts/fetch_boards.py                    # public boards, checked against boards/checksums.json
python3 pg/manufacturable.py --run <name> \
  [--pcb pg-n6=<board.kicad_pcb>]                  # a pg-hw board from a run (its .kicad_pro/.kicad_dru beside it)
  [--routed <dir>]                                 # a router's outputs, <dir>/<board>.kicad_pcb
```

**Set** (`boards/manifest-pg.json`): the pg-hw N6 mainboard (also CK1's mainboard: config/ck1.yaml
`case.mainboard.board: n6`) and Mossy1 quarter A from a pg-hw build (`PG_HW_BUILD` or `--pcb`);
zap25's eight 6-8 layer boards; eleven Antmicro 6-8 layer boards pinned to their default-branch HEAD on
2026-11-05 (Apache-2.0).

**Manufacturable** = 0 KiCad DRC errors + 0 unconnected items + pg-hw gates pass (pg boards only), where DRC
runs on a copy of the board with
- the board's own design-settings minima raised to the JLC 6-layer floors in `pg/jlc-6l.json` (never lowered),
- the fab-relevant checks in `severities_error` forced to error (a project cannot hide hole_to_hole as a warning),
- zones refilled. A board without its .kicad_pro is NO-PROJECT, not scored.

One row per board, appended to `results/<run>.tsv`:
`board layers nets drc_err unconnected gates seconds verdict top_errors`.

**Tier**: every board in the set is T0 (manifest `tier`): a routing test case only, never a source of copper,
blocks or layout priors. pg-hw boards become T1 once built and tested.

## Scoring a stage (`pg/stage_delta.py`)

```sh
python3 pg/stage_delta.py --stage <name> --board <board> --pcb <stage output.kicad_pcb> \
  [--window X0,Y0,X1,Y1] [--cert <certificate>] [--ref-run <run>]
```

Judges the stage output like `manufacturable.py` (rules from beside the output, else the reference's), within the
10 min budget, and compares each DRC error type and the unconnected count with the board's reference run
(pg boards: `2026-11-05-pg-boards`, others `2026-11-05-reference`), counting only violations with an item in the
window when one is given. **PASS** = no new type and no count above the reference; a type the reference has at
KiCad's 199 cap is CAPPED (not comparable). The absolute JLC verdict is the `jlc` column. Row appended to
`results/stages.tsv`; exit 0 only on PASS. Self-test (reference in = PASS, 20 segments cut = FAIL unconnected+11,
empty window = PASS): `results/2026-11-05-stage-selftest.tsv`.
