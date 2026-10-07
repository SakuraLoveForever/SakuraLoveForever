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

VERSION = "4.18.0"
SHANGHAI = timezone(timedelta(hours=8))
TOOLS = {"codex": ("Codex", "#7aa2f7"), "dsh": ("DeepSeek Harness", "#bb9af7")}
FIELDS = {"input": "input", "output": "output", "cache_read": "cacheRead",
          "cache_write": "cacheWrite", "reasoning": "reasoning"}


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
    if sum(row["active_ms"] for row in daily) != active_ms:
        raise ValueError("Active time daily sum does not match export total")
    return {"daily": daily, "active_ms": active_ms,
            "sessions": number(metrics["sessionCount"]),
            "max_concurrent_sessions": number(metrics["maxConcurrentSessions"])}


def check_history(previous, current):
    """Stop rather than silently publish reduced history after a log deletion."""
    for client in TOOLS:
        old = {row["date"]: row for row in previous["tools"][client]["daily"]}
        new = {row["date"]: row for row in current["tools"][client]["daily"]}
        for day, row in old.items():
            if (day not in new or new[day]["tokens"] < row["tokens"]
                    or new[day]["active_ms"] < row["active_ms"]):
                raise ValueError(f"History decreased for {client} on {day}; restore logs or review --allow-decrease")


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


def render_badges(root, data):
    # Shields.io renders its existing endpoint template; no custom SVG/layout.
    for client, (name, color) in TOOLS.items():
        tool = data["tools"][client]
        counts = {key: sum(row[key] for row in tool["daily"]) for key in FIELDS}
        values = {
            "tokens": sum(row["tokens"] for row in tool["daily"]),
            "input": counts["input"] + counts["cache_read"] + counts["cache_write"],
            "output": counts["output"] + counts["reasoning"],
            "cached": counts["cache_read"],
            "time": duration(tool["active_ms"]),
        }
        labels = {"tokens": "Tokens", "input": "Input", "output": "Output",
                  "cached": "Cached Input", "time": "Active Session Time"}
        for key, value in values.items():
            badge = {"schemaVersion": 1, "label": f"{name} {labels[key]}",
                     "message": f"{value:,}" if type(value) is int else value,
                     "color": color.lstrip("#")}
            atomic_write(root / "data/badges" / f"{client}-{key}.json",
                         json.dumps(badge, ensure_ascii=False, indent=2) + "\n")


def collect(args):
    config = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "SakuraLoveForever/usage-config"
    environment = dict(os.environ, TOKSCALE_CONFIG_DIR=str(config), TZ="Asia/Shanghai", NO_COLOR="1")
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    tools = {}

    def run(arguments):
        command = [npx, "--yes", f"tokscale@{VERSION}", *arguments]
        if args.home and arguments[0] != "config":
            command.extend(["--home", str(args.home)])
        subprocess.run(command, env=environment, check=True, capture_output=True, timeout=300)

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
                "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"), "tools": tools}
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    local = commands.add_parser("collect", help="Tokscale native scan + Wrapped, and Shields endpoint data")
    local.add_argument("--home", type=Path, help="Alternate home directory containing .codex/.dsh")
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
