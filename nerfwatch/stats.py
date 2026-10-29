"""Is today's run different from the baseline, or is it noise?

Pass/fail metrics use an exact stratified permutation test:
  - strata = suite items. Within one item, pool the baseline runs' outcomes and the
    current runs' outcomes. Under H0 ("nothing changed") the labels are exchangeable,
    so the number of current passes for that item is hypergeometric.
  - An item that always passes (or always fails) everywhere contributes zero variance,
    so a deterministic model's flips count heavily, and an item that already flaps
    in the baseline barely counts. Noise is measured per item from the repeats.
  - T = total current passes. Its null distribution is the convolution of the per-item
    hypergeometrics, computed exactly. Two-sided p-value. No sampling, no seed.
Continuous metrics (tokens, latency) use the same stratification with a seeded Monte
Carlo permutation on per-item log values.

A run is flagged CHANGED only if p < ALPHA *and* the effect is at least MIN_EFFECT,
so a significant-but-tiny shift (one item) is not called a nerf.
"""
import math
import random
from collections import defaultdict

ALPHA = 0.01
MIN_EFFECT = 0.03       # absolute change in pass rate (~1.3 items of 42)
MIN_RATIO = 0.15        # relative change in median tokens / latency


def _hypergeom_pmf(n, k, c):
    """P(X = x) for x current-passes when c of n pooled outcomes are current, k passes."""
    total = math.comb(n, c)
    return {x: math.comb(k, x) * math.comb(n - k, c - x) / total
            for x in range(max(0, c - (n - k)), min(k, c) + 1)}


def _convolve(a, b):
    out = defaultdict(float)
    for x, p in a.items():
        for y, q in b.items():
            out[x + y] += p * q
    return out


def _per_item(runs, key):
    by = defaultdict(list)
    for r in runs:
        for it in r["items"]:
            if it.get("error") or it.get(key) is None:
                continue
            by[it["id"]].append(it[key])
    return by


def binary_test(base_runs, cur_runs, key="pass", cats=None):
    """Exact stratified permutation test on a 0/1 item field. Returns dict."""
    def keep(run):
        if cats is None:
            return run
        return {**run, "items": [i for i in run["items"] if i["cat"] in cats]}
    b = _per_item([keep(r) for r in base_runs], key)
    c = _per_item([keep(r) for r in cur_runs], key)
    dist = {0: 1.0}
    t_obs = 0.0
    expected = 0.0
    base_rate_num = base_rate_den = cur_rate_num = cur_rate_den = 0
    for iid in sorted(set(b) & set(c)):
        bx, cx = b[iid], c[iid]
        n, k, nc = len(bx) + len(cx), sum(bx) + sum(cx), len(cx)
        dist = _convolve(dist, _hypergeom_pmf(n, k, nc))
        t_obs += sum(cx)
        expected += nc * k / n
        base_rate_num += sum(bx) / len(bx)
        base_rate_den += 1
        cur_rate_num += sum(cx) / len(cx)
        cur_rate_den += 1
    if not base_rate_den:
        return {"n_items": 0, "p": 1.0, "delta": 0.0, "base": None, "cur": None, "changed": False}
    dev = abs(t_obs - expected) - 1e-9
    p = sum(q for t, q in dist.items() if abs(t - expected) >= dev)
    base_rate = base_rate_num / base_rate_den
    cur_rate = cur_rate_num / cur_rate_den
    delta = cur_rate - base_rate
    return {"n_items": base_rate_den, "base": round(base_rate, 4), "cur": round(cur_rate, 4),
            "delta": round(delta, 4), "p": min(1.0, round(p, 6)),
            "changed": p < ALPHA and abs(delta) >= MIN_EFFECT}


def continuous_test(base_runs, cur_runs, key, n_perm=4000, seed=7):
    """Stratified permutation on per-item log(value). Effect = geometric-mean ratio."""
    b = _per_item(base_runs, key)
    c = _per_item(cur_runs, key)
    strata = []
    for iid in sorted(set(b) & set(c)):
        bx = [math.log(max(v, 1e-3)) for v in b[iid]]
        cx = [math.log(max(v, 1e-3)) for v in c[iid]]
        strata.append((bx + cx, len(cx)))
    if not strata:
        return {"ratio": 1.0, "p": 1.0, "changed": False}

    def stat(groups):
        s = 0.0
        for pooled, nc, cur in groups:
            s += sum(cur) / nc - (sum(pooled) - sum(cur)) / (len(pooled) - nc)
        return s / len(groups)

    obs = stat([(pool, nc, pool[len(pool) - nc:]) for pool, nc in strata])
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        g = []
        for pool, nc in strata:
            g.append((pool, nc, rng.sample(pool, nc)))
        if abs(stat(g)) >= abs(obs) - 1e-12:
            hits += 1
    p = (hits + 1) / (n_perm + 1)
    ratio = math.exp(obs)
    return {"ratio": round(ratio, 4), "p": round(p, 5),
            "changed": p < ALPHA and abs(ratio - 1) >= MIN_RATIO}


def compare(base_runs, cur_runs):
    return {
        "score": binary_test(base_runs, cur_runs, "pass"),
        "code": binary_test(base_runs, cur_runs, "pass", cats={"code"}),
        "instruct": binary_test(base_runs, cur_runs, "pass", cats={"instruct"}),
        "refusal": binary_test(base_runs, cur_runs, "refused", cats={"refuse"}),
        "over_refusal": binary_test(base_runs, cur_runs, "refused", cats={"comply"}),
        "tokens": continuous_test(base_runs, cur_runs, "completion_tokens"),
        "latency": continuous_test(base_runs, cur_runs, "latency_s"),
    }


def verdict(cmp):
    """One word for the dashboard. Latency alone never counts as a nerf (host noise)."""
    q = [cmp[k] for k in ("score", "code", "instruct")]
    if any(x["changed"] and x["delta"] < 0 for x in q):
        return "worse"
    if any(x["changed"] and x["delta"] > 0 for x in q):
        return "better"
    if cmp["refusal"]["changed"] or cmp["over_refusal"]["changed"] or cmp["tokens"]["changed"]:
        return "shifted"
    return "same"


def item_flips(runs):
    """Run-to-run noise: items whose pass/fail differs across repeated runs."""
    by = _per_item(runs, "pass")
    return sorted(iid for iid, xs in by.items() if 0 < sum(xs) < len(xs))
