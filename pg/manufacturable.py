#!/usr/bin/env python3
"""PitchGrid "manufacturable" judge (pg-hw #913): one line per board.

    BOARD_SET=pg [PG_HW_BUILD=<pg-hw build dir>] python3 pg/manufacturable.py [--run NAME] [--routed DIR] [board ...]

manufacturable = 0 KiCad DRC errors under the board's own rules raised to the JLC 6-layer floors (pg/jlc-6l.json;
a board's stricter minimum stays) + 0 unconnected items + the pg-hw gates (pg boards only: the gate JSON a pg-hw run
left in PG_HW_GATES, every "pass" true; other boards: n/a).

Board under test: <DIR>/<name>.kicad_pcb when --routed is given (a router's output), else the reference board
fetch_boards.py wrote (work/boards/<name>/circuit.reference.kicad_pcb); pg-hw boards come from PG_HW_BUILD + the
manifest's local.pcb. DRC runs on a copy in work/judge/<run>/<name>/ with zones refilled, errors only.
Rows go to results/<run>.tsv and stdout: board layers nets drc_err unconnected gates seconds verdict top_errors.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from common import ROOT, WORK, KICAD_CLI, board_dir, manifest  # noqa: E402

_J = json.load(open(os.path.join(ROOT, "pg", "jlc-6l.json")))
JLC, FAB_ERRORS = _J["rules"], _J["severities_error"]
OVERRIDE = {}  # --pcb name=path: judge this file for the board (its .kicad_pro/.kicad_dru beside it)
DRC_TIMEOUT = 1800  # stage_delta.py lowers it to its 10 min budget
COLS = ["board", "layers", "nets", "drc_err", "unconnected", "gates", "seconds", "verdict", "top_errors"]


def clamp_project(pro):
    """Raise the project's design-settings minima to the JLC floors (never lower one)."""
    with open(pro) as f:
        p = json.load(f)
    rules = p.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    raised = {}
    for k, v in JLC.items():
        if float(rules.get(k, 0) or 0) < v - 1e-9:
            raised[k] = (rules.get(k), v); rules[k] = v
    sev = p["board"]["design_settings"].setdefault("rule_severities", {})
    for k in FAB_ERRORS:
        if sev.get(k, "error") != "error":
            raised["severity:" + k] = (sev[k], "error"); sev[k] = "error"
    with open(pro, "w") as f:
        json.dump(p, f, indent=2)
    return raised


def source(b, routed):
    """(pcb, pro, dru) of the board under test."""
    n = b["name"]
    if n in OVERRIDE:
        st = OVERRIDE[n][: -len(".kicad_pcb")]
        return OVERRIDE[n], st + ".kicad_pro", st + ".kicad_dru"
    if routed:
        pcb = os.path.join(routed, n + ".kicad_pcb")
        ref = board_dir(n)
        return pcb, os.path.join(ref, "circuit.kicad_pro"), os.path.join(ref, "circuit.kicad_dru")
    if "local" in b:
        build = os.environ.get("PG_HW_BUILD")
        if not build:
            return None, None, None
        L = b["local"]
        return (os.path.join(build, L["pcb"]), os.path.join(build, L["pro"]), os.path.join(build, L.get("dru", "-")))
    d = board_dir(n)
    return os.path.join(d, "circuit.reference.kicad_pcb"), os.path.join(d, "circuit.kicad_pro"), os.path.join(d, "circuit.kicad_dru")


def gates(b):
    if b.get("origin") != "pg-hw":
        return "n/a"
    gdir = os.environ.get("PG_HW_GATES")
    if not gdir:
        return "missing"
    pre = {"pg-n6": "n6_", "pg-mossy-quarter-a": "mossy_quarter_"}[b["name"]]
    files = [f for f in glob.glob(os.path.join(gdir, "**", pre + "*.json"), recursive=True) if "selftest" not in f]
    if not files:
        return "missing"
    bad = []
    for f in files:
        try:
            j = json.load(open(f))
        except Exception:
            bad.append(os.path.basename(f)); continue
        if isinstance(j, dict) and j.get("pass") is False:
            bad.append(os.path.basename(f))
    return "pass" if not bad else "FAIL:" + ",".join(sorted(bad)[:4])


def nets_of(pcb):
    """Distinct net names on the board (KiCad 10 writes (net "name") on every item)."""
    import re
    with open(pcb, errors="replace") as f:
        return len(set(re.findall(r'\(net "([^"]+)"\)', f.read())) - {""})


def judge(b, run, routed):
    n = b["name"]
    pcb, pro, dru = source(b, routed)
    row = dict(board=n, layers=b.get("layers", "?"), nets="-", drc_err="-", unconnected="-", gates=gates(b), seconds="-", verdict="NO-BOARD", top_errors="")
    if not pcb or not os.path.exists(pcb):
        return row
    d = os.path.join(WORK, "judge", run, n)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    t = os.path.join(d, "board.kicad_pcb")
    shutil.copy(pcb, t)
    if not (pro and os.path.exists(pro)):
        row["verdict"] = "NO-PROJECT"  # without the board's rules KiCad judges by its defaults: not a score
        return row
    shutil.copy(pro, os.path.join(d, "board.kicad_pro"))
    if dru and os.path.exists(dru):
        shutil.copy(dru, os.path.join(d, "board.kicad_dru"))
    raised = clamp_project(os.path.join(d, "board.kicad_pro"))
    json.dump(raised, open(os.path.join(d, "jlc_raised.json"), "w"), indent=1)
    rep = os.path.join(d, "drc.json")
    t0 = time.time()
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-error", "--refill-zones", "-o", rep, t],
                   capture_output=True, text=True, timeout=DRC_TIMEOUT)
    row["seconds"] = round(time.time() - t0)
    row["nets"] = nets_of(t)
    if not os.path.exists(rep):
        row["verdict"] = "DRC-FAILED"; return row
    r = json.load(open(rep))
    by = {}
    for v in r.get("violations", []):
        if v.get("severity") == "error" and not v.get("excluded"):
            by[v.get("type", "?")] = by.get(v.get("type", "?"), 0) + 1
    unc = len(r.get("unconnected_items", []))
    row.update(drc_err=sum(by.values()), unconnected=unc,
               top_errors=",".join("%s=%d" % kv for kv in sorted(by.items(), key=lambda kv: -kv[1])[:4]))
    ok = row["drc_err"] == 0 and unc == 0 and row["gates"] in ("pass", "n/a")
    row["verdict"] = "MANUFACTURABLE" if ok else "no"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=time.strftime("%Y%m%d-%H%M") + "-reference")
    ap.add_argument("--routed")
    ap.add_argument("--pcb", action="append", default=[], help="name=path.kicad_pcb, e.g. a pg-hw board from a scratch run")
    ap.add_argument("boards", nargs="*")
    a = ap.parse_args()
    OVERRIDE.update(dict(x.split("=", 1) for x in a.pcb))
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    out = os.path.join(ROOT, "results", a.run + ".tsv")
    new = not os.path.exists(out)
    with open(out, "a") as f:
        if new:
            f.write("\t".join(COLS) + "\n")
        print("\t".join(COLS), flush=True)
        for b in manifest():
            if a.boards and b["name"] not in a.boards:
                continue
            row = judge(b, a.run, a.routed)
            line = "\t".join(str(row[c]) for c in COLS)
            f.write(line + "\n"); f.flush()
            print(line, flush=True)


if __name__ == "__main__":
    main()
