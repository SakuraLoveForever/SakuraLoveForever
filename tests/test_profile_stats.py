#!/usr/bin/env python3
"""End-to-end checks with small, hand-counted Tokscale and DSH exports (no private logs)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "profile_stats.py"


def export(client, tokens=325):
    return {
        "meta": {"version": "4.20.0"},
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


def dsh_export(days, providers, secret=None):
    """Local DSH scan output: one row per day, one entry per billing provider."""
    rows = [{"date": day, "tokens": tokens, "input": 100, "output": 20,
             "cache_read": 200, "cache_write": 0, "reasoning": 0}
            for day, tokens in days]
    graph = {"schema_version": 1, "timezone": "Asia/Shanghai", "source": "DSH session logs",
             "providers": providers, "daily": rows}
    if secret:
        graph["secretConversation"] = secret
    return graph


class ProfileStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.imports = self.root / "imports"
        self.imports.mkdir()
        (self.imports / "codex.json").write_text(json.dumps(export("codex")))
        (self.imports / "dsh.json").write_text(json.dumps(export("dsh")))
        self.write_dsh()

    def write_dsh(self, days=(("2026-10-01", 320),), bailian=5):
        providers = {"deepseek-official": {"tokens": sum(t for _, t in days) - bailian},
                     "aliyun-bailian": {"tokens": bailian}}
        (self.imports / "dsh-usage.json").write_text(
            json.dumps(dsh_export(days, providers, secret="private conversation body")))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root),
                               *args], capture_output=True, text=True, encoding="utf-8")

    def collect(self):
        return self.run_cli("collect", "--import-dir", str(self.imports))

    def test_collect_publishes_aggregates_only(self):
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
        self.assertNotIn("private conversation body", text)
        self.assertTrue((self.root / "data/badges/codex-tokens.json").exists())
        badge = json.loads((self.root / "data/badges/codex-tokens.json").read_text())
        self.assertEqual(badge["message"], "325")
        self.assertEqual(badge["label"], "Codex Tokens")
        self.assertFalse((self.root / "assets/ai-usage.svg").exists())

    def test_dsh_totals_come_from_the_local_scan_and_bailian_is_separate(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.root / "data/ai-usage.json").read_text(encoding="utf-8"))
        self.assertEqual(data["tools"]["dsh"]["daily"][0]["tokens"], 320)
        self.assertEqual(data["extra_tools"]["aliyun-bailian"]["daily"][0]["tokens"], 320)
        aliyun = json.loads((self.root / "data/badges/aliyun-tokens.json").read_text())
        self.assertEqual(aliyun["message"], "5")
        self.assertEqual(data["extra_tools"]["aliyun-bailian"]["total"], 5)

    def test_badges_are_one_total_and_clock_per_tool_with_snapshot_time(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        badges = self.root / "data/badges"
        self.assertEqual(sorted(p.name for p in badges.iterdir()),
                         ["aliyun-tokens.json", "codex-time.json", "codex-tokens.json",
                          "dsh-time.json", "dsh-tokens.json", "updated.json"])
        self.assertEqual(json.loads((badges / "codex-time.json").read_text())["message"], "0h 02m")
        snapshot = json.loads((self.root / "data/ai-usage.json").read_text())
        self.assertEqual(json.loads((badges / "updated.json").read_text())["message"],
                         snapshot["updated_at"])

    def test_bad_export_preserves_previous_snapshot_and_card(self):
        self.assertEqual(self.collect().returncode, 0)
        self.assertTrue((self.root / "data/badges/codex-tokens.json").exists())
        before = [(self.root / p).read_bytes() for p in
                  ("data/ai-usage.json", "data/badges/codex-tokens.json")]
        graph = json.loads((self.imports / "dsh-usage.json").read_text())
        graph["providers"]["aliyun-bailian"]["tokens"] = 6
        (self.imports / "dsh-usage.json").write_text(json.dumps(graph))
        result = self.collect()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provider total", result.stderr.lower())
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
