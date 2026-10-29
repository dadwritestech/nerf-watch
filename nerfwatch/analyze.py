"""Turn stored runs into per-target timelines with a changed-vs-baseline verdict per run."""
import statistics
from collections import defaultdict

from . import stats

BASELINE_RUNS = 5   # the first N runs of a target (same suite + temperature) are its baseline
MAX_ERROR_RATE = 0.1  # runs with more failed requests than this are infrastructure noise; skipped


def valid(run):
    s = run["summary"]
    return s["n_items"] and s["n_errors"] / s["n_items"] <= MAX_ERROR_RATE


def group(runs):
    g = defaultdict(list)
    for r in runs:
        g[(r["target"], r["suite_version"], r["temperature"])].append(r)
    return g


def timeline(target_runs, baseline_n=BASELINE_RUNS):
    """Each run gets a comparison. Baseline runs are tested leave-one-out against the
    other baseline runs, which is a direct false-positive check: they should all be 'same'."""
    target_runs = sorted(target_runs, key=lambda r: r["ts"])
    base = target_runs[:baseline_n]
    points = []
    for i, r in enumerate(target_runs):
        if i < len(base):
            ref = [b for b in base if b is not r]
            role = "baseline"
        else:
            ref = base
            role = "check"
        cmp = stats.compare(ref, [r]) if ref else None
        points.append({"run_id": r["run_id"], "ts": r["ts"], "role": role,
                       "summary": r["summary"], "cmp": cmp,
                       "verdict": stats.verdict(cmp) if cmp else "n/a"})
    return points


def noise_report(target_runs):
    s = [r["summary"]["score"] for r in target_runs if r["summary"]["score"] is not None]
    toks = [r["summary"]["median_tokens"] for r in target_runs if r["summary"]["median_tokens"]]
    return {
        "runs": len(target_runs),
        "score_mean": round(statistics.mean(s), 4) if s else None,
        "score_sd": round(statistics.stdev(s), 4) if len(s) > 1 else 0.0,
        "score_min": min(s) if s else None, "score_max": max(s) if s else None,
        "flapping_items": stats.item_flips(target_runs),
        "median_tokens_range": [min(toks), max(toks)] if toks else None,
    }


def build_report(runs, baseline_n=BASELINE_RUNS):
    targets = []
    drills = []
    skipped = [r["run_id"] for r in runs if not valid(r)]
    groups = group([r for r in runs if valid(r)])
    clean = {k: v for k, v in groups.items() if not v[0].get("drill")}
    for (name, sv, temp), rs in sorted(clean.items()):
        tl = timeline(rs, baseline_n)
        targets.append({"target": name, "model": rs[0]["model"], "suite_version": sv,
                        "temperature": temp, "points": tl, "noise": noise_report(rs),
                        "latest": tl[-1]["verdict"] if tl else "n/a"})
    # Drills: an injected degradation compared against the clean target's baseline.
    for (name, sv, temp), rs in sorted(groups.items()):
        if not rs[0].get("drill"):
            continue
        parent = rs[0]["drill"]
        base = sorted(groups.get((parent, sv, temp), []), key=lambda r: r["ts"])[:baseline_n]
        if not base:
            continue
        per_run = []
        for r in rs:
            cmp = stats.compare(base, [r])
            per_run.append({"run_id": r["run_id"], "summary": r["summary"], "cmp": cmp,
                            "verdict": stats.verdict(cmp)})
        drills.append({"target": name, "parent": parent, "system_prompt": rs[0].get("system_prompt"),
                       "temperature": temp, "runs": per_run})
    return {"targets": targets, "drills": drills, "skipped_runs": skipped, "alpha": stats.ALPHA,
            "min_effect": stats.MIN_EFFECT, "baseline_n": baseline_n}
