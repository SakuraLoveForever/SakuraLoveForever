"""Render dated Codex plan observations from local rollout logs."""
import argparse
import json
import os
import sys
from collections import defaultdict
from compression import zstd
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from profile_stats import SHANGHAI, atomic_write


PLANS = {'plus': ('Plus', '#7AA2F7'), 'prolite': ('Pro 100', '#BB9AF7'),
         'pro': ('Pro 200', '#E0AF68')}
LEFT, RIGHT, TRACK = 33, 867, 78
GAP_COLOR = '#788099'


def scan(home):
    observations = set()
    for folder in ('sessions', 'archived_sessions'):
        for path in (home / folder).rglob('rollout-*'):
            if path.name.endswith('.jsonl.zst'):
                source = zstd.open(path, 'rb')
            elif path.name.endswith('.jsonl'):
                source = path.open('rb')
            else:
                continue
            with source:
                for line in source:
                    if b'"plan_type"' not in line or b'"token_count"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        # The active rollout can end in a write still in progress.
                        continue
                    payload = event.get('payload', {})
                    if event.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                        continue
                    limits = payload.get('rate_limits') or {}
                    plan = limits.get('plan_type')
                    if limits.get('limit_id') != 'codex' or plan not in PLANS:
                        continue
                    day = datetime.fromisoformat(event['timestamp']).astimezone(SHANGHAI).date()
                    observations.add((day.isoformat(), plan))
    return sorted(observations)


def periods(observations):
    """Join same-plan readings, retaining gaps and overlapping transition dates."""
    days = defaultdict(set)
    for day, plan in observations:
        days[day].add(plan)
    result = []
    for day, plans in sorted(days.items()):
        # On a transition day extend the prior tier before starting the other tier.
        prior = result[-1][2] if result else None
        ordered = sorted(plans, key=lambda plan: (plan != prior, list(PLANS).index(plan)))
        for plan in ordered:
            if result and result[-1][2] == plan:
                result[-1] = (result[-1][0], day, plan)
            else:
                result.append((day, day, plan))
    return result


def render(rows):
    first, last = date.fromisoformat(rows[0][0]), date.fromisoformat(rows[-1][1])
    stop = last + timedelta(days=1)
    days = (stop - first).days

    def x(day):
        return LEFT + (RIGHT - LEFT) * (day - first).days / days

    def text(at, y, content, size=13, color='#B1BCD1', anchor='start', weight='400'):
        return (f'<text x="{at:.2f}" y="{y}" font-size="{size}" fill="{color}" '
                f'text-anchor="{anchor}" dominant-baseline="middle" font-weight="{weight}">'
                f'{escape(content)}</text>')

    year = str(first.year) if first.year == last.year else f'{first.year}–{last.year}'
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="164" '
        'viewBox="0 0 900 164" role="img" aria-labelledby="plan-title plan-description">',
        '<title id="plan-title">Codex 套餐时间线</title>',
        '<desc id="plan-description">本机日志记录的套餐观测日期。蓝色 Plus，紫色 Pro 100，'
        '金色 Pro 200，灰色虚线为不同套餐之间缺少记录的日期。观测范围可能包含同套餐的无活动日。</desc>',
        '<rect x="1" y="1" width="898" height="162" rx="16" fill="#161B27" stroke="#2A3346"/>',
        '<g font-family="Segoe UI, Microsoft YaHei, sans-serif">',
        text(LEFT, 26, 'Codex 套餐时间线', 21, '#E8EDF8', weight='700'),
        text(RIGHT, 26, f'{year} · 北京时间 · 本机日志观测', 12, anchor='end'),
    ]
    edges = []
    dates = [(date.fromisoformat(begin), date.fromisoformat(end)) for begin, end, _ in rows]

    def boundary(day, index, after=False):
        # Tiers sharing a transition date divide its width in observation order.
        touching = [row for row, (begin, end) in enumerate(dates) if begin <= day <= end]
        fraction = (touching.index(index) + int(after)) / len(touching)
        return x(day) + (RIGHT - LEFT) / days * fraction

    for index, (begin, end, plan) in enumerate(rows):
        start, finish = dates[index]
        left, right = boundary(start, index), boundary(finish, index, after=True)
        label, color = PLANS[plan]
        svg.append(f'<rect x="{left:.2f}" y="73.5" width="{right - left:.2f}" height="9" '
                   f'rx="4.5" fill="{color}"><title>{label} · {begin} — {end}</title></rect>')
        edges.extend((start, finish))
        if index + 1 < len(rows):
            next_start = date.fromisoformat(rows[index + 1][0])
            if finish + timedelta(days=1) < next_start:
                gap_start = finish + timedelta(days=1)
                gap_end = next_start - timedelta(days=1)
                svg.append(f'<path d="M {x(gap_start):.2f} {TRACK} H {x(next_start):.2f}" '
                           f'fill="none" stroke="{GAP_COLOR}" stroke-width="4" stroke-dasharray="3 4">'
                           f'<title>缺记录 · {gap_start} — {gap_end}</title></path>')

    # Keep endpoint labels and place close transition labels on the upper lane.
    candidates = set(edges)
    current = first.replace(day=1)
    while current <= last:
        if current >= first:
            candidates.add(current)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    occupied = {107: [LEFT, RIGHT], 54: []}
    endpoints = [first] if first == last else [first, last]
    for day in [*endpoints, *sorted(candidates - {first, last})]:
        at = LEFT if day == first else RIGHT if day == last else x(day)
        endpoint = day in (first, last)
        y = 107
        if not endpoint and any(abs(at - prior) < 48 for prior in occupied[y]):
            y = 54
            if any(abs(at - prior) < 48 for prior in occupied[y]):
                continue
        occupied[y].append(at)
        tick_start, tick_stop = (89, 95) if y == 107 else (67, 61)
        svg.append(f'<path d="M {at:.2f} {tick_start} V {tick_stop}" stroke="#49556C"/>')
        anchor = 'start' if day == first else 'end' if day == last else 'middle'
        svg.append(text(at, y, day.strftime('%m/%d'), anchor=anchor))

    at = LEFT
    for plan, (label, color) in PLANS.items():
        svg.append(f'<rect x="{at}" y="134" width="18" height="6" rx="3" fill="{color}"/>')
        svg.append(text(at + 26, 137, label, 14, '#D7DFF0'))
        at += 100 if plan == 'plus' else 126
    svg.append(f'<path d="M {at} 137 H {at + 18}" stroke="{GAP_COLOR}" stroke-width="3" stroke-dasharray="3 4"/>')
    svg.append(text(at + 26, 137, '缺记录', 14, '#D7DFF0'))
    return '\n'.join([*svg, '</g>', '</svg>', ''])


def refresh(root, home, state):
    previous = json.loads(state.read_text(encoding='utf-8'))['observations'] if state.exists() else []
    observations = sorted({(row['date'], row['plan']) for row in previous} | set(scan(home)))
    if not observations:
        raise ValueError('No Codex plan observations')
    rows = periods(observations)
    image = render(rows)
    atomic_write(state, json.dumps({'schema_version': 1, 'observations': [
        {'date': day, 'plan': plan} for day, plan in observations]}, indent=2) + '\n')
    atomic_write(root / 'assets/codex-plan-timeline.svg', image)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--home', type=Path, default=Path.home() / '.codex', help='Codex log directory')
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    parser.add_argument('--state', type=Path, default=local / 'SakuraLoveForever/codex-plan-observations.json')
    args = parser.parse_args()
    try:
        rows = refresh(args.root, args.home, args.state)
    except (OSError, ValueError, KeyError, zstd.ZstdError):
        print('Codex plan timeline failed. Check local logs and retained observations.', file=sys.stderr)
        return 1
    print(f'Refreshed Codex plan timeline ({rows[0][0]} to {rows[-1][1]}).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
