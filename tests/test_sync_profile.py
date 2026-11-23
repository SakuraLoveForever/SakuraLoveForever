"""Real Windows PowerShell 5.1 + Git publication against a temporary local remote."""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows scheduled publisher")
class PublishTests(unittest.TestCase):
    def test_midnight_publishes_each_successful_collector_and_retries_failures(self):
        for failed in ('activity', 'plans', 'both'):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory(prefix='sakura-midnight-test-') as temporary:
                root = Path(temporary)
                repo, remote = root / 'checkout', root / 'remote.git'
                scripts = repo / 'scripts'
                scripts.mkdir(parents=True)
                source = Path(__file__).resolve().parents[1]
                shutil.copyfile(source / 'scripts/sync-profile.ps1', scripts / 'sync-profile.ps1')
                (repo / '.gitignore').write_text('__pycache__/\n*.tmp\n')
                assets = repo / 'assets'
                assets.mkdir()
                names = ['codex-activity-daily.svg', 'codex-activity-weekly.svg',
                         'codex-activity-cumulative.svg', 'codex-plan-timeline.svg']
                for name in names:
                    (assets / name).write_text('old')
                for kind, outputs in [('activity', names[:3]), ('plans', names[3:])]:
                    (scripts / f'codex_{kind}.py').write_text(textwrap.dedent(f'''\
                        import os
                        from pathlib import Path
                        root = Path(__file__).resolve().parents[1]
                        if os.environ['FAILED_COLLECTOR'] in ('{kind}', 'both'):
                            raise SystemExit(1)
                        for name in {outputs!r}:
                            (root / 'assets' / name).write_text('new')
                        '''))

                def git(*args, cwd=repo):
                    return subprocess.run(['git', *args], cwd=cwd, check=True,
                                          capture_output=True, text=True).stdout

                git('init', '--initial-branch=main')
                git('config', 'user.name', 'Local test')
                git('config', 'user.email', 'test@example.invalid')
                git('add', '.')
                git('commit', '-m', 'seed')
                git('init', '--bare', '--initial-branch=main', str(remote))
                git('remote', 'add', 'origin', str(remote))
                git('push', '-u', 'origin', 'main')
                environment = dict(os.environ, LOCALAPPDATA=str(root / 'appdata'), FAILED_COLLECTOR=failed)
                result = subprocess.run(
                    ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                     str(scripts / 'sync-profile.ps1'), '-Publish', '-CodexActivity'],
                    env=environment, capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                for index, name in enumerate(names):
                    kind = 'activity' if index < 3 else 'plans'
                    expected = 'old' if failed in (kind, 'both') else 'new'
                    self.assertEqual(git('show', f'main:assets/{name}', cwd=remote), expected)
                self.assertEqual(git('status', '--porcelain').strip(), '')
                for path in root.rglob('*'):
                    if path.is_file():
                        path.chmod(0o666)

    def test_native_stderr_progress_does_not_interrupt_a_successful_git_push(self):
        with tempfile.TemporaryDirectory(prefix="sakura-publish-test-") as temporary:
            root = Path(temporary)
            repo, remote = root / "checkout", root / "remote.git"
            repo.mkdir()
            scripts = repo / "scripts"
            scripts.mkdir()
            source = Path(__file__).resolve().parents[1]
            shutil.copyfile(source / "scripts/sync-profile.ps1", scripts / "sync-profile.ps1")
            (scripts / "profile_stats.py").write_text(textwrap.dedent("""\
                import json
                import sys
                from pathlib import Path

                assert sys.argv[1:] == ["collect", "--codex-only"], sys.argv
                root = Path(__file__).resolve().parents[1]
                badges = root / "data/badges"
                badges.mkdir(parents=True)
                snapshot = {"tools": {"codex": {"active_ms": 120000}}}
                (root / "data/ai-usage.json").write_text(json.dumps(snapshot))
                for name in ("codex-tokens", "codex-time", "updated"):
                    (badges / (name + ".json")).write_text("{}\\n")
                (root / "assets").mkdir()
                (root / "assets/ai-usage.png").write_bytes(b"\\x89PNG\\r\\n\\x1a\\n")
                print("Collector progress", file=sys.stderr)
                """))
            (repo / ".gitignore").write_text("__pycache__/\n*.tmp\n")

            def git(*args, cwd=repo):
                return subprocess.run(["git", *args], cwd=cwd, check=True,
                                      capture_output=True, text=True)

            git("init", "--initial-branch=main")
            git("config", "user.name", "Local test")
            git("config", "user.email", "test@example.invalid")
            git("add", ".")
            git("commit", "-m", "seed")
            git("init", "--bare", "--initial-branch=main", str(remote))
            git("remote", "add", "origin", str(remote))
            git("push", "-u", "origin", "main")
            environment = dict(os.environ, LOCALAPPDATA=str(root / "appdata"))
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(scripts / "sync-profile.ps1"), "-Publish"],
                env=environment, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(git("status", "--porcelain").stdout.strip(), "")
            self.assertEqual(git("rev-parse", "HEAD").stdout,
                             git("rev-parse", "main", cwd=remote).stdout)
            data = json.loads(git("show", "main:data/ai-usage.json", cwd=remote).stdout)
            self.assertEqual(set(data["tools"]), {"codex"})
            self.assertTrue((repo / "assets/ai-usage.png").exists())
            # Windows Git sets read-only object bits; clear them for TemporaryDirectory cleanup.
            for path in root.rglob("*"):
                if path.is_file():
                    path.chmod(0o666)
