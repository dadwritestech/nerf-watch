"""nerf-watch CLI.

  python -m nerfwatch run    [--only NAME] [--reps N] [--temperature T]
  python -m nerfwatch drill  --parent NAME --system-prompt "..." [--reps N]
  python -m nerfwatch status
  python -m nerfwatch build  [--out site/index.html]
"""
import argparse
import json
import os
import sys

from . import analyze, dashboard, runner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nerfwatch")
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--targets", default=os.path.join(ROOT, "targets.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only", action="append", help="target name (repeatable)")
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--include-local", action="store_true",
                   help="run local targets too (they are skipped in CI by default)")
    d = sub.add_parser("drill", help="run a deliberately degraded copy of a target")
    d.add_argument("--parent", required=True)
    d.add_argument("--name", required=True)
    d.add_argument("--system-prompt", required=True)
    d.add_argument("--reps", type=int, default=1)
    d.add_argument("--temperature", type=float, default=0.0)
    sub.add_parser("status")
    sub.add_parser("noise", help="run-to-run noise + detection power per target")
    b = sub.add_parser("build")
    b.add_argument("--out", default=os.path.join(ROOT, "site", "index.html"))
    a = ap.parse_args(argv)

    if a.cmd == "run":
        targets = runner.load_targets(a.targets)
        ran = 0
        for t in targets:
            if a.only and t["name"] not in a.only:
                continue
            if t.get("local") and not (a.include_local or a.only):
                continue
            if not os.environ.get(t.get("api_key_env") or "") and not t.get("local"):
                print(f"skip {t['name']}: ${t.get('api_key_env')} not set")
                continue
            for i in range(a.reps):
                print(f"{t['name']} rep {i + 1}/{a.reps}")
                run = runner.run_target(t, a.data, temperature=a.temperature)
                print("  =>", json.dumps(run["summary"]))
                ran += 1
        print(f"{ran} run(s) written")
        return 0
    if a.cmd == "drill":
        t = next(t for t in runner.load_targets(a.targets) if t["name"] == a.parent)
        for i in range(a.reps):
            print(f"drill {a.name} rep {i + 1}/{a.reps}")
            run = runner.run_target(t, a.data, temperature=a.temperature,
                                    system_prompt=a.system_prompt, name=a.name, drill=a.parent)
            print("  =>", json.dumps(run["summary"]))
        return 0
    rep = analyze.build_report(runner.load_runs(a.data))
    if a.cmd == "status":
        worse = False
        for t in rep["targets"]:
            p = t["points"][-1]
            c = p["cmp"]["score"] if p["cmp"] else {}
            print(f"{t['target']:<40} T={t['temperature']} runs={len(t['points'])} "
                  f"latest={p['verdict']:<8} score={p['summary']['score']} "
                  f"delta={c.get('delta')} p={c.get('p')}")
            worse |= p["verdict"] == "worse"
        for d in rep["drills"]:
            for r in d["runs"]:
                c = r["cmp"]["score"]
                print(f"[drill] {d['target']:<32} vs {d['parent']}: {r['verdict']} "
                      f"delta={c['delta']} p={c['p']}")
        return 0
    if a.cmd == "noise":
        groups = analyze.group([r for r in runner.load_runs(a.data) if analyze.valid(r)])
        for (name, sv, temp), rs in sorted(groups.items()):
            if rs[0].get("drill") or len(rs) < 3:
                continue
            n = analyze.noise_report(rs)
            print(f"{name} T={temp}: {json.dumps(n)}")
            print("  detection rate when k items silently break (k: rate):",
                  json.dumps(analyze.power(rs)))
        return 0
    if a.cmd == "build":
        dashboard.build(rep, a.out)
        print("wrote", a.out)
        return 0


if __name__ == "__main__":
    sys.exit(main())
