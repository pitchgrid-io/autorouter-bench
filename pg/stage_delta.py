#!/usr/bin/env python3
"""One stage on one board (window): judge its output and write the delta row against the board's reference (pg-hw #913).

    BOARD_SET=pg BENCH_WORK=<work> python3 pg/stage_delta.py --stage <name> --board <board> --pcb <stage output .kicad_pcb>
        [--window X0,Y0,X1,Y1] [--cert <certificate path>] [--ref-run RUN]

The output is judged exactly like pg/manufacturable.py (JLC 6L floors, fab checks at error, zones refilled), with its
.kicad_pro/.kicad_dru taken from beside the output, else from the reference board. Then, per DRC error type and for
unconnected items, new = max(0, stage - reference), counting only violations with an item inside the window (mm, KiCad
page coordinates) when --window is given.

A stage PASSES a board (window) when it adds no new error type and no count over the reference. A type the reference has
at KiCad's report cap (>= 199) cannot be compared: the row says CAPPED for it and the verdict is at best "capped".
The absolute JLC verdict is reported beside it. The judge is held to the 10 min experiment budget.

Row appended to results/stages.tsv and printed:
    date stage board window cert drc_err ref_err unconnected ref_unc new jlc seconds verdict
"""
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import manufacturable as M  # noqa: E402
from common import ROOT, WORK, manifest  # noqa: E402

CAP = 199
BUDGET = 600
COLS = ["date", "stage", "board", "window", "cert", "drc_err", "ref_err", "unconnected", "ref_unc", "new", "jlc", "seconds", "verdict"]
REF_RUN = {"pg-hw": "2026-11-05-pg-boards"}  # by manifest origin; others "2026-11-05-reference"


def inside(v, win):
    if not win:
        return True
    x0, y0, x1, y1 = win
    return any(x0 <= i["pos"]["x"] <= x1 and y0 <= i["pos"]["y"] <= y1 for i in v.get("items", []) if "pos" in i)


def counts(rep, win):
    """({error type: n}, unconnected n) of a drc.json, window-filtered."""
    r = json.load(open(rep))
    by = {}
    for v in r.get("violations", []):
        if v.get("severity") == "error" and not v.get("excluded") and inside(v, win):
            by[v.get("type", "?")] = by.get(v.get("type", "?"), 0) + 1
    return by, sum(1 for v in r.get("unconnected_items", []) if inside(v, win))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--board", required=True)
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--window")
    ap.add_argument("--cert", default="-")
    ap.add_argument("--ref-run")
    a = ap.parse_args()
    b = next((x for x in manifest() if x["name"] == a.board), None)
    if not b:
        sys.exit("unknown board %s (BOARD_SET=pg?)" % a.board)
    win = tuple(float(x) for x in a.window.split(",")) if a.window else None
    ref_run = a.ref_run or REF_RUN.get(b.get("origin"), "2026-11-05-reference")
    ref = os.path.join(WORK, "judge", ref_run, a.board, "drc.json")
    if not os.path.exists(ref):
        sys.exit("no reference judge for %s at %s: run pg/manufacturable.py --run %s first" % (a.board, ref, ref_run))

    # Copy the output with its rules: .kicad_pro/.kicad_dru beside it, else the reference judge's copy of the board's.
    pcb = os.path.abspath(a.pcb)
    d = os.path.join(WORK, "stage-in", a.stage + "-" + time.strftime("%Y%m%d-%H%M%S"), a.board)
    os.makedirs(d, exist_ok=True)
    shutil.copy(pcb, os.path.join(d, a.board + ".kicad_pcb"))
    for ext in ("pro", "dru"):
        mine, theirs = pcb[: -len("kicad_pcb")] + "kicad_" + ext, os.path.join(os.path.dirname(ref), "board.kicad_" + ext)
        src = mine if os.path.exists(mine) else theirs
        if os.path.exists(src):
            shutil.copy(src, os.path.join(d, a.board + ".kicad_" + ext))
    M.OVERRIDE[a.board] = os.path.join(d, a.board + ".kicad_pcb")

    M.DRC_TIMEOUT = BUDGET
    run = "stage-%s-%s" % (a.stage, time.strftime("%Y%m%d-%H%M%S"))
    row = dict(date=time.strftime("%Y-%m-%d %H:%M"), stage=a.stage, board=a.board,
               window=a.window or "board", cert=a.cert)
    try:
        j = M.judge(b, run, None)
    except Exception as e:  # subprocess.TimeoutExpired included
        j = dict(verdict="JUDGE-" + type(e).__name__, seconds=BUDGET)
    row.update(jlc=j["verdict"], seconds=j.get("seconds", "-"))
    rep = os.path.join(WORK, "judge", run, a.board, "drc.json")
    if not os.path.exists(rep):
        row.update(drc_err="-", ref_err="-", unconnected="-", ref_unc="-", new="-", verdict=j["verdict"])
    else:
        sb, su = counts(rep, win)
        rb, ru = counts(ref, win)
        new, capped = [], []
        for t in sorted(set(sb) | set(rb)):
            if rb.get(t, 0) >= CAP:
                capped.append(t)
            elif sb.get(t, 0) > rb.get(t, 0):
                new.append("%s+%d" % (t, sb[t] - rb.get(t, 0)))
        if su > ru:
            new.append("unconnected+%d" % (su - ru))
        row.update(drc_err=sum(sb.values()), ref_err=sum(rb.values()), unconnected=su, ref_unc=ru,
                   new=",".join(new + ["CAPPED:" + t for t in capped]) or "none",
                   verdict="FAIL" if new else ("capped" if capped else "PASS"))
    out = os.path.join(ROOT, "results", "stages.tsv")
    first = not os.path.exists(out)
    with open(out, "a") as f:
        if first:
            f.write("\t".join(COLS) + "\n")
        f.write("\t".join(str(row[c]) for c in COLS) + "\n")
    print("\t".join(COLS))
    print("\t".join(str(row[c]) for c in COLS))
    sys.exit(0 if row["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
