"""Publish aggregate-only profile statistics; private transcripts stay on this PC."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = "4.20.0"
SHANGHAI = timezone(timedelta(hours=8))
TOOLS = {"codex": ("Codex", "#7aa2f7"), "dsh": ("DeepSeek Harness", "#bb9af7")}
# DSH generations routed through Alibaba Bailian; collected from the same local logs by
# scripts/collect-aliyun-usage.js, not by Tokscale (it reports no token counts for them).
ALIYUN = ("aliyun-bailian", "DeepSeek (Bailian)", "#ff9e64")
FIELDS = {"input": "input", "output": "output", "cache_read": "cacheRead",
          "cache_write": "cacheWrite", "reasoning": "reasoning"}
LABELS = {"tokens": "Tokens", "time": "使用时长"}


def number(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a non-negative integer statistic")
    return value


def normalize(graph, client):
    if graph["meta"]["version"] != VERSION:
        raise ValueError(f"Expected Tokscale {VERSION}; review schema before upgrading")
    daily = []
    for row in graph["contributions"]:
        day = date.fromisoformat(row["date"]).isoformat()
        if day > datetime.now(SHANGHAI).date().isoformat():
            raise ValueError("Unexpected future date in usage history")
        if any(item["client"] != client for item in row["clients"]):
            raise ValueError("Unexpected client in filtered export")
        counts = {key: number(row["tokenBreakdown"][source]) for key, source in FIELDS.items()}
        tokens = number(row["totals"]["tokens"])
        if sum(counts.values()) != tokens:
            raise ValueError("Token breakdown does not match daily total")
        daily.append({"date": day, "tokens": tokens, **counts,
                      "active_ms": number(row["activeTimeMs"])})
    daily.sort(key=lambda row: row["date"])
    if len({row["date"] for row in daily}) != len(daily):
        raise ValueError("Duplicate date in usage history")
    if sum(row["tokens"] for row in daily) != number(graph["summary"]["totalTokens"]):
        raise ValueError("Token daily sum does not match export total")
    metrics = graph["timeMetrics"]
    active_ms = number(metrics["totalActiveTimeMs"])
    # Tokscale floors per-day active time; the total may exceed the sum by a few ms.
    if abs(sum(row["active_ms"] for row in daily) - active_ms) > 1000:
        raise ValueError("Active time daily sum does not match export total")
    return {"daily": daily, "active_ms": active_ms,
            "sessions": number(metrics["sessionCount"]),
            "max_concurrent_sessions": number(metrics["maxConcurrentSessions"])}


def normalize_aliyun(graph):
    if graph["provider"] != ALIYUN[0] or graph["timezone"] != "Asia/Shanghai":
        raise ValueError("Unexpected provider in Bailian usage export")
    daily = []
    for row in graph["daily"]:
        day = date.fromisoformat(row["date"]).isoformat()
        if day > datetime.now(SHANGHAI).date().isoformat():
            raise ValueError("Unexpected future date in Bailian usage history")
        counts = {key: number(row[key]) for key in FIELDS}
        tokens = number(row["tokens"])
        if sum(counts.values()) != tokens:
            raise ValueError("Token breakdown does not match Bailian daily total")
        daily.append({"date": day, "tokens": tokens, **counts, "active_ms": 0})
    daily.sort(key=lambda row: row["date"])
    if len({row["date"] for row in daily}) != len(daily):
        raise ValueError("Duplicate date in Bailian usage history")
    return {"daily": daily, "active_ms": 0}


def check_history(previous, current):
    """Stop rather than silently publish reduced history after a log deletion."""
    seen = 0
    for client in TOOLS:
        seen += compare_days(client, previous["tools"][client]["daily"],
                             current["tools"][client]["daily"])
    provider = ALIYUN[0]
    if provider in previous.get("extra_tools", {}):
        seen += compare_days(provider, previous["extra_tools"][provider]["daily"],
                             current["extra_tools"][provider]["daily"])
    if not seen and previous.get("tools"):
        raise ValueError("Usage history disappeared entirely; restore logs or review --allow-decrease")


def compare_days(client, earlier, later):
    old = {row["date"]: row for row in earlier}
    new = {row["date"]: row for row in later}
    for day, row in old.items():
        if (day not in new or new[day]["tokens"] < row["tokens"]
                or new[day]["active_ms"] < row["active_ms"]):
            raise ValueError(f"History decreased for {client} on {day}; restore logs or review --allow-decrease")
    return len(old)


def atomic_write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(contents, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def duration(milliseconds):
    minutes = milliseconds // 60000
    return f"{minutes // 60}h {minutes % 60:02d}m"


def badge_values(tool):
    counts = {key: sum(row[key] for row in tool["daily"]) for key in FIELDS}
    values = {
        "tokens": sum(row["tokens"] for row in tool["daily"]),
        "noncache": counts["input"] + counts["output"] + counts["reasoning"],
        "input": counts["input"] + counts["cache_read"] + counts["cache_write"],
        "output": counts["output"] + counts["reasoning"],
        "cached": counts["cache_read"],
        "time": duration(tool["active_ms"]),
    }
    return values


def render_badges(root, data):
    # Shields.io renders its existing endpoint template; no custom SVG/layout.
    # Per tool: a token total and a session clock; no cache split.
    for client, (name, color) in TOOLS.items():
        values = badge_values(data["tools"][client])
        for key in ("tokens", "time"):
            value = values[key]
            atomic_write(root / "data/badges" / f"{client}-{key}.json", json.dumps({
                "schemaVersion": 1, "label": f"{name} {LABELS[key]}",
                "message": f"{value:,}" if type(value) is int else value,
                "color": color.lstrip("#")}, ensure_ascii=False, indent=2) + "\n")
    provider, name, color = ALIYUN
    if provider in data.get("extra_tools", {}):
        # Only the total: the split endpoints are published in the JSON, not as badges.
        total = badge_values(data["extra_tools"][provider])["tokens"]
        atomic_write(root / "data/badges/aliyun-tokens.json", json.dumps({
            "schemaVersion": 1, "label": f"{name} {LABELS['tokens']}", "message": f"{total:,}",
            "color": color.lstrip("#")}, indent=2) + "\n")
    atomic_write(root / "data/badges/updated.json", json.dumps({
        "schemaVersion": 1, "label": "AI usage updated", "message": data["updated_at"],
        "color": "7aa2f7",
    }, indent=2) + "\n")


def collect_aliyun(args, temporary):
    """Node.js (bundled with the Tokscale toolchain) reads the same local DSH logs."""
    path = args.import_dir / "aliyun-bailian.json" if args.import_dir else None
    if not path:
        node = shutil.which("node")
        if not node:
            raise ValueError("Node.js is required to aggregate Alibaba Bailian usage")
        path = Path(temporary) / "aliyun-bailian.json"
        script = Path(__file__).resolve().parent / "collect-aliyun-usage.js"
        command = [node, str(script), "--out", str(path)]
        if args.home:
            command.append(str(args.home))
        command.extend(str(extra) for extra in args.import_home or [])
        result = subprocess.run(command, capture_output=True, timeout=300,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"Bailian usage collection failed ({result.returncode}): {diagnostics[-4000:]}")
    if not path.exists():
        return {}
    graph = json.loads(path.read_text(encoding="utf-8-sig"))
    return {ALIYUN[0]: normalize_aliyun(graph)}


def collect(args):
    config = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "SakuraLoveForever/usage-config"
    environment = dict(os.environ, TOKSCALE_CONFIG_DIR=str(config), TZ="Asia/Shanghai", NO_COLOR="1")
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    tools = {}

    def run(arguments):
        command = [npx, "--yes", f"tokscale@{VERSION}", *arguments]
        if args.home and arguments[0] != "config":
            command.extend(["--home", str(args.home)])
        result = subprocess.run(command, env=environment, capture_output=True, timeout=300,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode:
            raise ValueError(f"Tokscale {arguments[0]} failed ({result.returncode}): {diagnostics[-4000:]}")
        if diagnostics:
            print(diagnostics, file=sys.stderr)

    if not args.import_dir:
        if not npx:
            raise ValueError("Node.js/npm is required to run the pinned Tokscale CLI")
        run(["config", "set", "timezone", "Asia/Shanghai"])
        # DSH desktop uses a different home from the CLI. Let Tokscale scan and dedupe it.
        roaming = args.home / "AppData/Roaming" if args.home else Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        candidates = [roaming / "dsh-desktop/harness/sessions",
                      roaming / "@deepseek-ai/dsh-desktop/harness/sessions"]
        settings_path = config / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        extra = settings.setdefault("scanner", {}).setdefault("extraScanPaths", {}).setdefault("dsh", [])
        for candidate in candidates:
            if candidate.is_dir() and str(candidate) not in extra:
                extra.append(str(candidate))
        atomic_write(settings_path, json.dumps(settings, indent=2) + "\n")

    with tempfile.TemporaryDirectory(prefix="sakura-usage-") as temporary:
        for client in TOOLS:
            if args.import_dir:
                path = args.import_dir / f"{client}.json"
            else:
                path = Path(temporary) / f"{client}.json"
                run(["graph", "--client", client, "--output", str(path), "--no-spinner"])
            tools[client] = normalize(json.loads(path.read_text(encoding="utf-8-sig")), client)
        data = {"schema_version": 1, "timezone": "Asia/Shanghai", "source": f"tokscale@{VERSION}",
                "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"), "tools": tools,
                "extra_tools": collect_aliyun(args, temporary)}
        previous = args.root / "data/ai-usage.json"
        if previous.exists() and not args.allow_decrease:
            check_history(json.loads(previous.read_text(encoding="utf-8")), data)
        if not args.import_dir:
            image = Path(temporary) / "ai-usage.png"
            run(["wrapped", "--client", "codex,dsh", "--clients", "--year",
                 str(datetime.now(SHANGHAI).year), "--output", str(image), "--no-spinner"])
            if image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Tokscale did not produce a valid PNG")
            destination = args.root / "assets/ai-usage.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged = destination.with_suffix(".png.tmp")
            shutil.copyfile(image, staged)
            staged.replace(destination)
        render_badges(args.root, data)
        atomic_write(previous, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    for client, tool in tools.items():
        days = tool["daily"]
        coverage = f"{days[0]['date']} to {days[-1]['date']}" if days else "no usage recorded"
        print(f'{TOOLS[client][0]}: {sum(row["tokens"] for row in days):,} tokens; '
              f'{duration(tool["active_ms"])} active session time; {coverage}')
    for provider, tool in data["extra_tools"].items():
        days = tool["daily"]
        coverage = f"{days[0]['date']} to {days[-1]['date']}" if days else "no usage recorded"
        print(f'{ALIYUN[1]}: {sum(row["tokens"] for row in days):,} tokens; {coverage}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    local = commands.add_parser("collect", help="Tokscale native scan + Wrapped, and Shields endpoint data")
    local.add_argument("--home", type=Path, help="Alternate home directory containing .codex/.dsh")
    local.add_argument("--import-home", type=Path, help="Extra user home whose DSH logs hold Bailian usage")
    local.add_argument("--import-dir", type=Path, help="Offline codex.json/dsh.json exports; update badges only")
    local.add_argument("--allow-decrease", action="store_true", help="Accept a reviewed historical correction")
    commands.add_parser("render", help="Refresh Shields endpoint JSON from existing aggregate data")
    args = parser.parse_args()
    if args.command == "collect":
        collect(args)
    else:
        data = json.loads((args.root / "data/ai-usage.json").read_text(encoding="utf-8"))
        render_badges(args.root, data)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"Profile stats update failed: {error}", file=sys.stderr)
        sys.exit(1)
