"""Real Windows PowerShell 5.1 + Git publication against a temporary local remote."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows scheduled publisher")
class PublishTests(unittest.TestCase):
    def test_native_stderr_progress_does_not_interrupt_a_successful_git_push(self):
        with tempfile.TemporaryDirectory(prefix="sakura-publish-test-") as temporary:
            root = Path(temporary)
            repo, remote = root / "checkout", root / "remote.git"
            repo.mkdir()
            scripts = repo / "scripts"
            scripts.mkdir()
            source = Path(__file__).resolve().parents[1]
            for name in ("sync-profile.ps1", "profile_stats.py"):
                shutil.copyfile(source / "scripts" / name, scripts / name)
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
            self.assertEqual(set(data["tools"]), {"codex", "dsh"})
            self.assertTrue((repo / "assets/ai-usage.png").exists())
            # Windows Git sets read-only object bits; clear them for TemporaryDirectory cleanup.
            for path in root.rglob("*"):
                if path.is_file():
                    path.chmod(0o666)
