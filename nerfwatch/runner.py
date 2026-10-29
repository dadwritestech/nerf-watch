"""Run the suite against targets and append results under data/."""
import csv
import datetime as dt
import json
import os
import re
import statistics

from . import suite
from .client import ChatError, chat
from .score import score_item, word_count

CSV_FIELDS = ["run_id", "ts", "date", "target", "model", "suite_version", "temperature", "drill",
              "n_items", "n_errors", "score", "code", "instruct", "refuse_rate", "over_refusal",
              "code_partial", "median_tokens", "median_words", "median_latency_s", "tok_per_s"]


def load_targets(path):
    """Targets from targets.json, or a single ad-hoc target from env vars:
    NERFWATCH_BASE_URL, NERFWATCH_MODEL, NERFWATCH_API_KEY (+ optional NERFWATCH_NAME)."""
    if os.environ.get("NERFWATCH_BASE_URL"):
        model = os.environ["NERFWATCH_MODEL"]
        return [{"name": os.environ.get("NERFWATCH_NAME", model),
                 "base_url": os.environ["NERFWATCH_BASE_URL"], "model": model,
                 "api_key_env": "NERFWATCH_API_KEY"}]
    with open(path, encoding="utf-8") as f:
        return json.load(f)["targets"]


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def summarize(results):
    ok = [r for r in results if not r.get("error")]

    def rate(cat, key="pass"):
        xs = [r[key] for r in ok if r["cat"] == cat]
        return round(sum(xs) / len(xs), 4) if xs else None

    toks = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
    lat = [r["latency_s"] for r in ok]
    tps = [r["completion_tokens"] / r["latency_s"] for r in ok
           if r.get("completion_tokens") and r["latency_s"] > 0]
    partial = [r["partial"] for r in ok if r["cat"] == "code"]
    return {
        "n_items": len(results), "n_errors": len(results) - len(ok),
        "score": round(sum(r["pass"] for r in ok) / len(ok), 4) if ok else None,
        "code": rate("code"), "instruct": rate("instruct"),
        "refuse_rate": rate("refuse", "refused"), "over_refusal": rate("comply", "refused"),
        "code_partial": round(sum(partial) / len(partial), 4) if partial else None,
        "median_tokens": statistics.median(toks) if toks else None,
        "median_words": statistics.median([r["words"] for r in ok]) if ok else None,
        "median_latency_s": round(statistics.median(lat), 3) if lat else None,
        "tok_per_s": round(statistics.median(tps), 2) if tps else None,
    }


def run_target(target, data_dir, temperature=0.0, seed=1234, system_prompt=None, name=None,
               drill=False, now=None, log=print, item_filter=None):
    key = os.environ.get(target.get("api_key_env") or "", "") or None
    name = name or target["name"]
    items = suite.items()
    if item_filter:
        items = [i for i in items if item_filter(i)]
    results = []
    for it in items:
        rec = {"id": it["id"], "cat": it["cat"]}
        try:
            r = chat(target["base_url"], target["model"], it["prompt"], api_key=key,
                     max_tokens=it["max_tokens"], temperature=temperature, seed=seed,
                     system_prompt=system_prompt or target.get("system_prompt"),
                     extra_body=target.get("extra_body"))
        except ChatError as e:
            rec.update({"error": str(e)[:300], "pass": 0})
            results.append(rec)
            log(f"  {it['id']:<22} ERROR {str(e)[:80]}")
            continue
        sc = score_item(it, r["text"])
        rec.update(sc)
        rec.update({"latency_s": r["latency_s"], "completion_tokens": r["completion_tokens"],
                    "prompt_tokens": r["prompt_tokens"], "finish_reason": r["finish_reason"],
                    "words": word_count(r["text"])})
        # Never store what a model says to a harmful prompt; store everything else for audit.
        rec["text"] = None if it["cat"] == "refuse" else r["text"][:4000]
        results.append(rec)
        log(f"  {it['id']:<22} {'PASS' if sc['pass'] else 'fail'}  {r['completion_tokens']} tok  {r['latency_s']}s")

    now = now or dt.datetime.now(dt.timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run = {"run_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-{slug(name)}", "ts": ts,
           "date": ts[:10], "target": name, "model": target["model"],
           "suite_version": suite.SUITE_VERSION, "temperature": temperature, "seed": seed,
           "drill": drill, "system_prompt": system_prompt or target.get("system_prompt"),
           "summary": summarize(results), "items": results}
    save_run(run, data_dir)
    return run


def save_run(run, data_dir):
    day = os.path.join(data_dir, "runs", run["date"])
    os.makedirs(day, exist_ok=True)
    with open(os.path.join(day, run["run_id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(run, f, indent=1, ensure_ascii=False)
    path = os.path.join(data_dir, "results.csv")
    new = not os.path.exists(path)
    row = {k: run.get(k) for k in CSV_FIELDS}
    row.update({k: v for k, v in run["summary"].items() if k in CSV_FIELDS})
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def load_runs(data_dir):
    runs = []
    root = os.path.join(data_dir, "runs")
    if not os.path.isdir(root):
        return runs
    for day in sorted(os.listdir(root)):
        for fn in sorted(os.listdir(os.path.join(root, day))):
            if fn.endswith(".json"):
                with open(os.path.join(root, day, fn), encoding="utf-8") as f:
                    runs.append(json.load(f))
    runs.sort(key=lambda r: r["ts"])
    return runs
