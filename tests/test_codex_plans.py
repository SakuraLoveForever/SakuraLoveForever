"""Codex tier observations use only structured quota events and retain local history."""
import json
import sys
import tempfile
import unittest
from compression import zstd
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_plans


def event(day, plan, limit_id='codex'):
    return {'type': 'event_msg', 'timestamp': day + 'T12:00:00Z', 'payload': {
        'type': 'token_count', 'rate_limits': {'limit_id': limit_id, 'plan_type': plan},
        'private': 'private prompt and account@example.invalid'}}


class CodexPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'codex'
        self.sessions = self.home / 'sessions'
        self.sessions.mkdir(parents=True)
        self.state = self.root / 'private-state.json'

    def test_compressed_archived_events_filter_client_and_private_content(self):
        archive = self.home / 'archived_sessions'
        archive.mkdir()
        content = b''.join((json.dumps(row) + '\n').encode() for row in [
            event('2026-11-07', 'prolite'), event('2026-11-08', 'pro', 'spark'),
            event('2026-11-09', 'free'), event('2026-11-10', 'plus', None),
            {'type': 'response_item', 'timestamp': '2026-11-11T00:00:00Z',
             'payload': event('2026-11-11', 'pro')},
        ])
        (archive / 'rollout-one.jsonl.zst').write_bytes(zstd.compress(content) + zstd.compress(
            (json.dumps(event('2026-11-15', 'pro')) + '\n').encode()))
        (self.sessions / 'rollout-copy.jsonl').write_text(
            json.dumps(event('2026-11-07', 'prolite')) + '\n', encoding='utf-8')
        rows = codex_plans.scan(self.home)
        self.assertEqual(rows, [('2026-11-07', 'prolite'), ('2026-11-15', 'pro')])
        codex_plans.refresh(self.root, self.home, self.state)
        state = self.state.read_text(encoding='utf-8')
        svg = (self.root / 'assets/codex-plan-timeline.svg').read_text(encoding='utf-8')
        self.assertNotIn('private prompt', state + svg)
        self.assertNotIn('account@example.invalid', state + svg)
        self.assertEqual(set(json.loads(state)), {'schema_version', 'observations'})
        ElementTree.fromstring(svg)

    def test_periods_keep_shared_day_gap_and_return_to_prior_plan(self):
        rows = [('2026-08-20', 'plus'), ('2026-11-04', 'plus'),
                ('2026-11-07', 'prolite'), ('2026-11-15', 'prolite'),
                ('2026-11-15', 'pro'), ('2026-11-24', 'pro'),
                ('2026-12-01', 'plus')]
        periods = codex_plans.periods(rows)
        self.assertEqual(periods, [
            ('2026-08-20', '2026-11-04', 'plus'),
            ('2026-11-07', '2026-11-15', 'prolite'),
            ('2026-11-15', '2026-11-24', 'pro'),
            ('2026-12-01', '2026-12-01', 'plus'),
        ])
        svg = codex_plans.render(periods)
        self.assertIn('2026-11-05 — 2026-11-06', svg)
        self.assertIn('2026-11-07 — 2026-11-15', svg)
        self.assertIn('Pro 100', svg)
        self.assertIn('Pro 200', svg)
        self.assertEqual(svg.count('stroke-dasharray='), 3)
        self.assertIn('2026–2027', codex_plans.render([
            ('2026-12-30', '2026-12-31', 'plus'), ('2027-01-01', '2027-01-02', 'pro')]))
        ElementTree.fromstring(svg)

    def test_refresh_retains_observations_after_source_rotation_and_is_deterministic(self):
        source = self.sessions / 'rollout-one.jsonl'
        source.write_text(json.dumps(event('2026-08-20', 'plus')) + '\n', encoding='utf-8')
        codex_plans.refresh(self.root, self.home, self.state)
        source.write_text(json.dumps(event('2026-11-24', 'pro')) + '\n', encoding='utf-8')
        codex_plans.refresh(self.root, self.home, self.state)
        svg = (self.root / 'assets/codex-plan-timeline.svg').read_bytes()
        self.assertIn(b'2026-08-20', svg)
        self.assertIn(b'2026-11-24', svg)
        codex_plans.refresh(self.root, self.home, self.state)
        self.assertEqual((self.root / 'assets/codex-plan-timeline.svg').read_bytes(), svg)

    def test_one_day_has_one_date_label_and_all_observed_tiers_are_visible(self):
        rows = [('2026-11-24', '2026-11-24', plan) for plan in ('plus', 'prolite', 'pro')]
        root = ElementTree.fromstring(codex_plans.render(rows))
        self.assertEqual(list(root.itertext()).count('11/24'), 1)
        rectangles = root.findall('.//{http://www.w3.org/2000/svg}rect')
        segments = [rect for rect in rectangles if rect.get('y') == '73.5']
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(float(rect.get('width')) > 0 for rect in segments))

    def test_corrupt_compressed_input_preserves_previous_output_and_state(self):
        source = self.sessions / 'rollout-one.jsonl'
        source.write_text(json.dumps(event('2026-11-24', 'pro')) + '\n', encoding='utf-8')
        codex_plans.refresh(self.root, self.home, self.state)
        svg = self.root / 'assets/codex-plan-timeline.svg'
        before = (self.state.read_bytes(), svg.read_bytes())
        (self.sessions / 'rollout-corrupt.jsonl.zst').write_bytes(b'corrupt')
        with self.assertRaises(zstd.ZstdError):
            codex_plans.refresh(self.root, self.home, self.state)
        self.assertEqual((self.state.read_bytes(), svg.read_bytes()), before)
