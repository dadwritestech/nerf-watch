"""nerf-watch feed for herald: only check runs whose score changed significantly vs the baseline.
Baseline runs never post (they are the false-positive check), and neither does latency alone."""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from nerfwatch import analyze, runner  # noqa: E402

SITE = "https://dadwritestech.github.io/nerf-watch"


def main():
    report = analyze.build_report(runner.load_runs(os.path.join(ROOT, "data")))
    for t in report["targets"]:
        for p in t["points"]:
            if p["role"] != "check" or p["verdict"] not in ("worse", "better"):
                continue
            c = p["cmp"]["score"]
            word = "dropped" if p["verdict"] == "worse" else "rose"
            print(json.dumps({
                "id": f"nerf-watch/{p['run_id']}",
                "text": (f"{t['target']} {word} on today's check: {abs(c['delta']) * 100:.1f} points "
                         f"vs its baseline (p={c['p']}, {t['noise']['runs']} runs on record, "
                         f"same prompts, temperature {t['temperature']}). One run is a signal, not a verdict."),
                "link": SITE,
                "priority": 6 if p["verdict"] == "worse" else 4,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
