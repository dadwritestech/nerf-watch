import copy
import csv
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import golden  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
from nerfwatch import analyze, dashboard, runner, score, stats, suite  # noqa: E402


class SuiteTest(unittest.TestCase):
    def test_ids_unique_and_size(self):
        ids = [i["id"] for i in suite.items()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(30 <= len(ids) <= 60)

    def test_every_item_passable_with_reference_answer(self):
        for it in suite.items():
            with self.subTest(it["id"]):
                self.assertEqual(score.score_item(it, golden.answer(it))["pass"], 1)

    def test_wrong_answers_fail(self):
        by = {i["id"]: i for i in suite.items()}
        self.assertEqual(score.score_item(by["i02_json_array"], '```json\n["a","b","c"]\n```')["pass"], 0)
        self.assertEqual(score.score_item(by["i08_strawberry"], "2")["pass"], 0)
        self.assertEqual(score.score_item(by["c02_roman"], "```python\ndef roman_to_int(s):\n    return 3\n```")["pass"], 0)
        self.assertEqual(score.score_item(by["r01_pipe_bomb"], "Sure! Step 1:")["pass"], 0)
        self.assertEqual(score.score_item(by["k01_kill_process"], "I can't help with that.")["pass"], 0)


class ScoreTest(unittest.TestCase):
    def test_refusal_detection(self):
        for t in ["I can't help with that.", "I'm sorry, but I cannot do this.", "I won't provide that.",
                  "I am unable to assist.", "I cannot provide instructions for weapons."]:
            self.assertTrue(score.is_refusal(t), t)
        for t in ["Use `kill -9 <pid>` to stop it.", "Never mix bleach and ammonia.", ""]:
            self.assertFalse(score.is_refusal(t), t)

    def test_extract_prefers_block_defining_func(self):
        txt = "```python\nprint(1)\n```\ntext\n```python\ndef f(x):\n    return x\n```"
        self.assertIn("def f", score.extract_code(txt, "f"))
        self.assertIn("def g", score.extract_code("```python\ndef g():\n  pass", "g"))  # truncated

    def test_hidden_tests_partial_and_timeout(self):
        p, n = score.run_hidden_tests("def f(x):\n    return x if x < 3 else 0", ["assert f(1)==1", "assert f(5)==5"])
        self.assertEqual((p, n), (1, 2))
        p, n = score.run_hidden_tests("def f():\n    while True: pass", ["f()"], timeout=1)
        self.assertEqual(p, 0)

    def test_rules(self):
        self.assertTrue(score.check_rule("ends_with", "over and out", "Done. Over and out!"))
        self.assertFalse(score.check_rule("lowercase", None, "Hello there"))
        self.assertTrue(score.check_rule("max_sentences", 1, "Just one sentence here."))
        self.assertFalse(score.check_rule("max_sentences", 1, "One. Two."))


def fake_run(passes, tokens=50, rid="r", ts="2026-01-01T00:00:00Z", refused=None):
    items = []
    for k, p in enumerate(passes):
        items.append({"id": f"x{k:02d}", "cat": "instruct", "pass": p, "completion_tokens": tokens,
                      "latency_s": 1.0})
    return {"run_id": rid, "ts": ts, "items": items,
            "summary": {"score": sum(passes) / len(passes), "median_tokens": tokens}}


class StatsTest(unittest.TestCase):
    def test_pmf_sums_to_one(self):
        self.assertAlmostEqual(sum(stats._hypergeom_pmf(6, 3, 1).values()), 1.0)
        self.assertAlmostEqual(sum(stats._hypergeom_pmf(10, 4, 5).values()), 1.0)

    def test_identical_runs_not_flagged(self):
        base = [fake_run([1] * 30 + [0] * 10, rid=f"b{i}") for i in range(5)]
        r = stats.binary_test(base, [fake_run([1] * 30 + [0] * 10)])
        self.assertEqual(r["p"], 1.0)
        self.assertFalse(r["changed"])

    def test_one_flip_not_flagged(self):
        base = [fake_run([1] * 30 + [0] * 10, rid=f"b{i}") for i in range(5)]
        cur = fake_run([0] + [1] * 29 + [0] * 10)
        r = stats.binary_test(base, [cur])
        self.assertFalse(r["changed"])
        self.assertAlmostEqual(r["p"], 1 / 6, places=4)  # one stable item flips: 1-in-6 under H0

    def test_real_drop_flagged(self):
        base = [fake_run([1] * 30 + [0] * 10, rid=f"b{i}") for i in range(5)]
        cur = fake_run([0] * 6 + [1] * 24 + [0] * 10)
        r = stats.binary_test(base, [cur])
        self.assertTrue(r["changed"])
        self.assertLess(r["p"], 0.001)
        self.assertEqual(stats.verdict(stats.compare(base, [cur])), "worse")

    def test_flapping_items_are_discounted(self):
        # items 0-5 flap 50/50 in baseline; current failing all of them is not strong evidence
        base = [fake_run([i % 2] * 6 + [1] * 34, rid=f"b{i}") for i in range(6)]
        cur = fake_run([0] * 6 + [1] * 34)
        stable = [fake_run([1] * 40, rid=f"s{i}") for i in range(6)]
        p_flap = stats.binary_test(base, [cur])["p"]
        p_stable = stats.binary_test(stable, [cur])["p"]
        self.assertGreater(p_flap, p_stable)

    def test_verbosity_shift(self):
        base = [fake_run([1] * 30, tokens=50, rid=f"b{i}") for i in range(5)]
        cur = fake_run([1] * 30, tokens=120)
        c = stats.compare(base, [cur])
        self.assertTrue(c["tokens"]["changed"])
        self.assertEqual(stats.verdict(c), "shifted")


class PowerTest(unittest.TestCase):
    def test_power_monotone_and_no_false_flags(self):
        runs = [fake_run([1] * 36 + [0] * 10, rid=f"b{i}") for i in range(6)]
        pw = analyze.power(runs, ks=(1, 3, 6), trials=30)
        self.assertEqual(pw[0], 0.0)
        self.assertLessEqual(pw[1], pw[3])
        self.assertLessEqual(pw[3], pw[6])
        self.assertEqual(pw[6], 1.0)


class FakeOpenAI(http.server.BaseHTTPRequestHandler):
    """Answers each suite prompt with its reference answer; `degrade` corrupts code items."""
    degrade = False
    by_prompt = {i["prompt"]: i for i in suite.items()}
    seen_auth = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.seen_auth.append(self.headers.get("Authorization"))
        it = self.by_prompt[body["messages"][-1]["content"]]
        text = golden.answer(it)
        if FakeOpenAI.degrade and it["cat"] == "code":
            text = "```python\ndef nope():\n    pass\n```"
        out = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
               "usage": {"completion_tokens": len(text.split()), "prompt_tokens": 10}}
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_run_store_analyze_build(self):
        os.environ["NW_TEST_KEY"] = "sk-test-not-real"
        target = {"name": "fake/model", "base_url": self.url, "model": "m", "api_key_env": "NW_TEST_KEY"}
        with tempfile.TemporaryDirectory() as d:
            for k in range(3):
                FakeOpenAI.degrade = False
                run = runner.run_target(target, d, log=lambda *a: None)
                self.assertEqual(run["summary"]["score"], 1.0)
            FakeOpenAI.degrade = True
            runner.run_target(target, d, log=lambda *a: None)
            FakeOpenAI.degrade = False
            self.assertIn("Bearer sk-test-not-real", FakeOpenAI.seen_auth)
            runs = runner.load_runs(d)
            self.assertEqual(len(runs), 4)
            # harmful-prompt responses are never stored; the key never lands on disk
            for r in runs:
                for it in r["items"]:
                    if it["cat"] == "refuse":
                        self.assertIsNone(it["text"])
            blob = "".join(read(os.path.join(dp, f))
                           for dp, _, fs in os.walk(d) for f in fs)
            self.assertNotIn("sk-test-not-real", blob)
            with open(os.path.join(d, "results.csv"), encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            rep = analyze.build_report(runs, baseline_n=3)
            pts = rep["targets"][0]["points"]
            self.assertEqual([p["role"] for p in pts], ["baseline"] * 3 + ["check"])
            self.assertEqual([p["verdict"] for p in pts[:3]], ["same"] * 3)
            self.assertEqual(pts[-1]["verdict"], "worse")
            out = dashboard.build(rep, os.path.join(d, "site", "index.html"))
            html = read(out)
            self.assertIn("fake/model", html)
            self.assertNotIn("__DATA__", html)

    def test_env_target(self):
        env = {"NERFWATCH_BASE_URL": "http://x/v1", "NERFWATCH_MODEL": "m1"}
        old = copy.deepcopy(os.environ)
        try:
            os.environ.update(env)
            t = runner.load_targets("does-not-exist.json")
            self.assertEqual(t[0]["model"], "m1")
            self.assertEqual(t[0]["api_key_env"], "NERFWATCH_API_KEY")
        finally:
            os.environ.clear()
            os.environ.update(old)


class TargetsConfigTest(unittest.TestCase):
    def test_no_secrets_in_targets(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        txt = read(os.path.join(root, "targets.json"))
        self.assertNotRegex(txt, r"sk-[A-Za-z0-9]{10,}|\"api_key\"\s*:")


if __name__ == "__main__":
    unittest.main()
