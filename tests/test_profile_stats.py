"""End-to-end checks with small, hand-counted Tokscale exports (no private logs)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "profile_stats.py"


def export(client, tokens=325):
    return {
        "meta": {"version": "4.18.0"},
        "summary": {"totalTokens": tokens},
        "contributions": [{
            "date": "2026-10-01", "totals": {"tokens": tokens},
            "tokenBreakdown": {"input": 100, "output": 20, "cacheRead": 200,
                               "cacheWrite": 0, "reasoning": 5},
            "clients": [{"client": client, "modelId": "private-model-name"}],
            "activeTimeMs": 120000,
        }],
        "timeMetrics": {"totalActiveTimeMs": 120000, "sessionCount": 2,
                        "maxConcurrentSessions": 2},
        "secretConversation": "must never be published",
    }


class ProfileStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.imports = self.root / "imports"
        self.imports.mkdir()
        for client in ("codex", "dsh"):
            (self.imports / f"{client}.json").write_text(json.dumps(export(client)))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root),
                               *args], capture_output=True, text=True, encoding="utf-8")

    def collect(self):
        return self.run_cli("collect", "--import-dir", str(self.imports))

    def test_collect_counts_cache_once_and_publishes_only_aggregates(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.root / "data/ai-usage.json").read_text(encoding="utf-8")
        data = json.loads(text)
        day = data["tools"]["codex"]["daily"][0]
        self.assertEqual(day["tokens"], 325)
        self.assertEqual(day["input"], 100)
        self.assertEqual(day["cache_read"], 200)
        self.assertNotIn("private-model-name", text)
        self.assertNotIn("must never be published", text)
        self.assertTrue((self.root / "data/badges/codex-tokens.json").exists())
        badge = json.loads((self.root / "data/badges/codex-tokens.json").read_text())
        self.assertEqual(badge["message"], "325")
        badge = json.loads((self.root / "data/badges/codex-input.json").read_text())
        self.assertEqual(badge["message"], "300")  # input including cache
        badge = json.loads((self.root / "data/badges/codex-output.json").read_text())
        self.assertEqual(badge["message"], "25")  # output including reasoning
        self.assertFalse((self.root / "assets/ai-usage.svg").exists())

    def test_bad_export_preserves_previous_snapshot_and_card(self):
        self.assertEqual(self.collect().returncode, 0)
        self.assertTrue((self.root / "data/badges/codex-tokens.json").exists())
        before = [(self.root / p).read_bytes() for p in
                  ("data/ai-usage.json", "data/badges/codex-tokens.json")]
        (self.imports / "dsh.json").write_text(json.dumps(export("dsh", tokens=326)))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("token", result.stderr.lower())
        after = [(self.root / p).read_bytes() for p in
                 ("data/ai-usage.json", "data/badges/codex-tokens.json")]
        self.assertEqual(after, before)

    def test_disappearing_history_cannot_silently_reduce_totals(self):
        self.assertEqual(self.collect().returncode, 0)
        before = (self.root / "data/ai-usage.json").read_bytes()
        graph = export("codex")
        graph["contributions"] = []
        graph["summary"]["totalTokens"] = 0
        graph["timeMetrics"]["totalActiveTimeMs"] = 0
        (self.imports / "codex.json").write_text(json.dumps(graph))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("history", result.stderr.lower())
        self.assertEqual((self.root / "data/ai-usage.json").read_bytes(), before)

    def test_time_history_cannot_decrease_when_tokens_are_unchanged(self):
        self.assertEqual(self.collect().returncode, 0)
        before = (self.root / "data/ai-usage.json").read_bytes()
        graph = export("codex")
        graph["contributions"][0]["activeTimeMs"] = 0
        graph["timeMetrics"]["totalActiveTimeMs"] = 0
        (self.imports / "codex.json").write_text(json.dumps(graph))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("history", result.stderr.lower())
        self.assertEqual((self.root / "data/ai-usage.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
