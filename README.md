# nerf-watch

**"Did they nerf it today?" answered with data instead of vibes.**

A fixed, deterministic canary suite runs against a model every day. It's scored by rules only (no LLM judge), results are committed as plain JSON/CSV, and a static dashboard flags a model only when the change is **statistically distinguishable from that model's own measured run-to-run noise**.

> **Status: v0, local only.** Every number below was measured on a local llama-server. **No vendor (Claude/GPT/Gemini) data exists yet**: those targets are config slots that run only when a key is present. No numbers are invented.

![dashboard](docs/dashboard.png)

## What it measures

46 items, frozen as suite `2026-10-29.1` ([nerfwatch/suite.py](nerfwatch/suite.py)):

| Category | Items | Pass means |
|---|---|---|
| Coding | 16 | the model's function passes **hidden** asserts (never shown in the prompt), each run in a fresh `python -I` with a 10 s timeout |
| Instruction following | 20 | every exact rule holds: regex fullmatch, JSON parses to 3 strings, exactly 7 words, all lowercase, no letter "e", ... |
| Refusal | 5 | clearly harmful asks are refused (detected by phrase rules; **responses are never stored**) |
| Over-refusal | 5 | benign asks with scary words ("kill a Python process") are answered |
| Every item | 46 | completion tokens, words, latency |

`tests/golden.py` holds a reference answer for every item, and the tests prove every one of them passes. No item is impossible, and no check is broken.

## How "changed" is decided

Per target, the first 5 runs are the **baseline**. Each later run is compared to it with an **exact stratified permutation test** ([nerfwatch/stats.py](nerfwatch/stats.py)):

- Strata are the suite items. Within one item, baseline and current outcomes are pooled and the run labels are exchangeable under "nothing changed", so the current pass count is hypergeometric.
- An item that passes (or fails) in every run carries no noise, so a flip there counts heavily. An item that already flips during the baseline barely counts.
- The null distribution is the exact convolution of the per-item hypergeometrics, so the p-value is exact and uses no random sampling.
- A run is flagged only if **p < 0.01 and** the pass rate moves at least **3 points**. Verbosity uses the same stratification on log tokens (flag at ≥15%). Latency is shown but **never** counts as a nerf, because it measures the host as much as the model.

Baseline runs are also tested leave-one-out against each other. That gives a direct false-positive check: they should all come out "same".

## Measured so far (2026-10-29)

**ministral-3-3b-instruct (Q4_K_M), local llama-server, temperature 0, seed 1234, 6 runs:**

| | |
|---|---|
| Pass rate | **74.3%** mean (73.9 – 76.1), run-to-run SD **0.9 pts** |
| Coding / instruction | 81.3% (all runs) / 60–65% |
| Refuses harmful | 80% (4/5: it answered the stalkerware ask in every run) |
| Over-refusal | 0% |
| Median completion tokens | 54 – 55.5 |
| Median latency | 4.35 s → 8.69 s (same model, same prompts; the server got busier) |
| False flags | **0 of 6** held-out runs |

**Temperature 0 is not deterministic on a shared server.** With temperature 0 and a fixed seed, only **21 of 41** stored answers were byte-identical across all 6 runs. Requests from other sessions shared the batches. Most of that drift doesn't change the verdict; only **2 items flipped pass/fail**:

- `i08_strawberry` ("how many r's"): answered `1` four times and `3` twice.
- `i03_seven_words`: once inserted an extra "endless", giving 8 words.

This is why one run is never enough, and why the test weighs each item by its own flip rate.

**Detection power, measured on the real runs.** Hold one real run out, silently break *k* of its passing items, and test it against the other five (`python -m nerfwatch noise`):

| items broken (k) | 0 | 1 | 2 | 3 | 4 | 5 | 6+ |
|---|---|---|---|---|---|---|---|
| pass-rate drop | – | 2.2 pts | 4.3 | 6.5 | 8.7 | 10.9 | ≥13 |
| flagged | **0%** | 0% | 0% | 7.5% | **84%** | **100%** | 100% |

In plain terms: with a 5-run baseline, this suite reliably catches a regression of **4–5 items (≈9–11 points)** and stays quiet about 1–3. A smaller regression needs more items or more runs per day. That trade-off is the honest price of not crying wolf.

### Not measured yet (blocked)

On 2026-10-29 the shared local llama-server stopped completing requests at about 09:15 UTC. Every backend reported `/health ok`, but no request finished and the GPUs sat idle. Before that, gemma-4-12b's only slot was taken by another workload's 4k-token jobs. So the following are still missing:

- a **second model** (gemma-4-12b or hearthfire-24b);
- **temperature 0.7** noise runs;
- **drills**: the same model with an injected degrading system prompt, which the detector should flag.

All of it is one command: [`scripts/resume_campaign.sh`](scripts/resume_campaign.sh).

## Usage

```bash
python -m nerfwatch run --only local/ministral-3-3b --reps 3
```

```bash
python -m nerfwatch status
```

```bash
python -m nerfwatch noise
```

```bash
python -m nerfwatch build
```

Targets live in [targets.json](targets.json): any OpenAI-compatible endpoint. The key comes from the env var named in `api_key_env` and is never written anywhere. For a one-off target, set `NERFWATCH_BASE_URL`, `NERFWATCH_MODEL` and `NERFWATCH_API_KEY`. Targets with no key are skipped and never faked.

Data layout: one JSON per run in `data/runs/<date>/` (scores, tokens and latency per item, plus answer text except for harmful prompts), and one row per run in `data/results.csv`.

Daily CI: [.github/workflows/daily.yml](.github/workflows/daily.yml) runs the tests, then the suite against every target whose key secret exists, then commits `data/` and `site/`. It's written but **not enabled**: the repo isn't pushed and no secrets exist.

Zero dependencies: Python 3.10+ standard library only.

```bash
python -m unittest discover -s tests
```

## Limits

- Refusal detection is phrase-based. It's stable over time, which a canary needs, but it isn't a safety evaluation.
- 46 items can't see a 1-item regression. That's by design (see the power table) and can be traded for more items or more runs.
- Ministral fails 11 items in every run, and gemma-4-12b passed all 42 items of the earlier 42-item draft in a calibration run. The 4 harder items were added for headroom, but strong models will sit near the ceiling, where improvements are invisible and only drops show. For a nerf detector that's the right direction.
- Latency on a shared host is mostly noise about the host.
