"""Render the Codex Profile's account token activity for the GitHub README."""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from itertools import accumulate
from pathlib import Path
from threading import Timer

from profile_stats import SHANGHAI, atomic_write, number


WEEKS = 53
LEFT = 64
STEP = 20
COLORS = ('#303030', '#3f2268', '#6136a6', '#9359ed', '#c196ff')


def read_usage():
    """Read account aggregates over the official app-server stdio transport."""
    with subprocess.Popen(
        ['codex', 'app-server', '--stdio'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    ) as process:
        def send(message):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()

        def receive(request_id):
            for line in process.stdout:
                response = json.loads(line)
                if response.get('id') == request_id:
                    if 'error' in response:
                        raise ValueError('Codex app-server refused the request')
                    return response['result']
            raise ValueError('Codex app-server closed or timed out')

        timeout = Timer(30, process.kill)
        timeout.start()
        try:
            send({'method': 'initialize', 'id': 0, 'params': {'clientInfo': {
                'name': 'github_profile_activity', 'title': 'GitHub Profile Activity', 'version': '1.0.0',
            }}})
            receive(0)
            send({'method': 'initialized'})
            send({'method': 'account/usage/read', 'id': 1})
            return receive(1)
        finally:
            timeout.cancel()
            process.kill()


def read_buckets(usage):
    buckets = usage['dailyUsageBuckets']
    if not isinstance(buckets, list) or not buckets:
        raise ValueError('Daily usage buckets are unavailable')
    daily = {}
    for bucket in buckets:
        day = date.fromisoformat(bucket['startDate'])
        if day in daily:
            raise ValueError('Duplicate daily usage bucket')
        daily[day] = number(bucket['tokens'])
    summary = usage.get('summary')
    lifetime = summary.get('lifetimeTokens') if summary is not None else None
    return daily, number(lifetime) if lifetime is not None else None


def label(x, y, content, fill='#a3a3a3', size=18):
    return f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}">{content}</text>'


def card(title, subtitle, graphic):
    return '\n'.join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1172" height="282" '
        'viewBox="0 0 1172 282" role="img" aria-labelledby="activity-title">',
        f'<title id="activity-title">{title} · {subtitle}</title>',
        '<rect width="1172" height="282" rx="16" fill="#181818"/>',
        '<g font-family="Segoe UI, Microsoft YaHei, system-ui, sans-serif">',
        label(LEFT, 63, title, '#fafafa', 22), label(LEFT, 91, subtitle, '#a3a3a3', 15),
        *graphic, '</g>', '</svg>', '',
    ])


def refresh(root, usage, as_of):
    daily, lifetime = read_buckets(usage)
    first = as_of - timedelta(days=7 * (WEEKS - 1) + as_of.weekday())
    days = [first + timedelta(days=offset) for offset in range((as_of - first).days + 1)]
    peak = max(daily.get(day, 0) for day in days)
    daily_graph = []
    month = None
    for offset, day in enumerate(days):
        column, row = divmod(offset, 7)
        x = LEFT + column * STEP
        tokens = daily.get(day, 0)
        level = 1 + sum(tokens * 4 > peak * level for level in range(1, 4)) if tokens else 0
        daily_graph.append(f'<rect x="{x}" y="{108 + row * STEP}" width="16" height="16" '
                           f'rx="4" fill="{COLORS[level]}"><title>{day} · {tokens:,}</title></rect>')
        if day.month != month:
            month = day.month
            # A rolling window can start and end in the same month; avoid cramped end labels.
            if column < WEEKS - 1 and (offset == 0 or column > 1):
                daily_graph.append(label(x, 263, f'{month}月'))

    starts = days[::7]
    weekly = [sum(daily.get(day, 0) for day in days[offset:offset + 7])
              for offset in range(0, len(days), 7)]
    weekly_peak = max(weekly) or 1
    weekly_graph = []
    for column, (week, tokens) in enumerate(zip(starts, weekly)):
        height = max(2, round(132 * tokens / weekly_peak))
        weekly_graph.append(f'<rect x="{LEFT + column * STEP}" y="{240 - height}" width="16" '
                            f'height="{height}" rx="4" fill="{COLORS[3] if tokens else COLORS[0]}">'
                            f'<title>{week} · {tokens:,}</title></rect>')

    cumulative = list(accumulate(weekly))
    window_tokens = cumulative[-1]
    coordinates = ' '.join(f'{LEFT + column * STEP + 8},{240 - round(132 * tokens / (window_tokens or 1))}'
                           for column, tokens in enumerate(cumulative))
    cumulative_graph = [f'<polyline points="{coordinates}" fill="none" stroke="{COLORS[-1]}" '
                        'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>']
    interval = label(LEFT, 263, f'{first} — {as_of}')
    lifetime_label = f' · 账号累计 {lifetime:,}' if lifetime is not None else ''
    views = {
        'daily': card('Codex Token 活动', '每天 · 最近约一年', daily_graph),
        'weekly': card('Codex Token 活动', '每周 · 周一开始', [*weekly_graph, interval]),
        'cumulative': card('Codex Token 活动', f'窗口内累计 {window_tokens:,}{lifetime_label}',
                           [*cumulative_graph, interval]),
    }
    for name, image in views.items():
        atomic_write(root / 'assets' / f'codex-activity-{name}.svg', image)


def main():
    try:
        usage = read_usage()
        refresh(Path(__file__).resolve().parents[1], usage, datetime.now(SHANGHAI).date())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Keep account payloads and app-server diagnostics out of the sync log.
        print('Codex activity sync failed. Check Codex CLI, ChatGPT sign-in, and network.', file=sys.stderr)
        return 1
    print('Refreshed Codex account activity charts.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
