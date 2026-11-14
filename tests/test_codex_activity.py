import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_activity


class CodexActivityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_daily_dates_week_totals_and_lifetime_render_from_account_buckets(self):
        codex_activity.refresh(self.root, {
            'summary': {'lifetimeTokens': 501},
            'dailyUsageBuckets': [
                {'startDate': '2026-11-08', 'tokens': 7},
                {'startDate': '2026-11-09', 'tokens': 11},
                {'startDate': '2026-11-11', 'tokens': 13},
            ],
        }, date(2026, 11, 12))
        activity = self.root / 'assets'
        daily = ''.join(ElementTree.parse(activity / 'codex-activity-daily.svg').getroot().itertext())
        weekly = ''.join(ElementTree.parse(activity / 'codex-activity-weekly.svg').getroot().itertext())
        cumulative = ''.join(ElementTree.parse(activity / 'codex-activity-cumulative.svg').getroot().itertext())
        self.assertIn('2026-11-08 · 7', daily)
        self.assertIn('2026-11-10 · 0', daily)
        self.assertNotIn('2026-11-13', daily)
        self.assertIn('2026-11-02 · 7', weekly)
        self.assertIn('2026-11-09 · 24', weekly)
        self.assertIn('31', cumulative)
        self.assertIn('501', cumulative)

    def test_unavailable_or_duplicate_buckets_preserve_published_assets(self):
        assets = self.root / 'assets'
        assets.mkdir()
        last_good = assets / 'codex-activity-daily.svg'
        last_good.write_bytes(b'last good asset')
        repeated = {'startDate': '2026-11-08', 'tokens': 7}
        for daily in (None, [repeated, repeated]):
            with self.subTest(daily=daily), self.assertRaises(ValueError):
                codex_activity.refresh(self.root, {'summary': {}, 'dailyUsageBuckets': daily},
                                       date(2026, 11, 12))
        self.assertEqual(last_good.read_bytes(), b'last good asset')
        self.assertEqual(list(assets.iterdir()), [last_good])
