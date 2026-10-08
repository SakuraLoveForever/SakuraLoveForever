"""Execute the actual 3D workflow publication commands against a local Git remote."""
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH = shutil.which("bash") if os.name != "nt" else shutil.which("bash", path=r"C:\Program Files\Git\bin")


@unittest.skipUnless(BASH, "Bash is required by the GitHub runner")
class ProfilePublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="profile-git-test-")
        self.addCleanup(self.cleanup)
        self.root = Path(self.temporary.name)
        self.repo, self.remote = self.root / "checkout", self.root / "remote.git"
        self.repo.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "README.md").write_text("seed\n")
        (self.repo / "profile-3d-contrib").mkdir()
        (self.repo / "profile-3d-contrib/profile.svg").write_text("<svg>seed</svg>\n")
        self.git("add", ".")
        self.git("commit", "-m", "seed")
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")

    def cleanup(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(0o666)
        self.temporary.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo,
                              check=True, capture_output=True, text=True).stdout

    def generate(self):
        folder = self.repo / "profile-3d-contrib"
        folder.mkdir(exist_ok=True)
        (folder / "profile.svg").write_text("<svg/>\n")

    def publish(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/profile-3d.yml"
        script = textwrap.dedent(workflow.read_text().split("      - name: Commit & Push\n", 1)[1].split("        run: |\n", 1)[1])
        return subprocess.run([BASH, "-e", "-o", "pipefail", "-c", script],
                              cwd=self.repo, env=dict(os.environ, GITHUB_REF_NAME="main"),
                              capture_output=True, text=True, timeout=30)

    def test_commit_failure_is_reported_as_failure(self):
        self.generate()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assertNotEqual(self.publish().returncode, 0)

    def test_publication_preserves_a_concurrent_metrics_commit(self):
        other = self.root / "other"
        self.git("clone", str(self.remote), str(other))
        (other / "metrics.svg").write_text("<svg>metrics</svg>\n")
        self.git("add", ".", cwd=other)
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "metrics", cwd=other)
        self.git("push", cwd=other)
        self.generate()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("show", "main:metrics.svg", cwd=self.remote), "<svg>metrics</svg>\n")
        self.assertEqual(self.git("show", "main:profile-3d-contrib/profile.svg", cwd=self.remote), "<svg/>\n")

    def test_unchanged_assets_do_not_create_a_commit(self):
        before = self.git("rev-parse", "HEAD")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
