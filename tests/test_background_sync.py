"""Exercise the real windowless Windows entry point without collecting or publishing."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows background launcher")
class BackgroundSyncTests(unittest.TestCase):
    def test_hidden_entry_preserves_arguments_and_failure_exit_code(self):
        source = Path(__file__).resolve().parents[1] / "scripts/sync-profile-background.vbs"
        self.assertTrue(source.exists(), "Scheduled sync needs a windowless entry point")
        with tempfile.TemporaryDirectory(prefix="profile background test ") as temporary:
            folder = Path(temporary)
            launcher = folder / source.name
            shutil.copyfile(source, launcher)
            (folder / "sync-profile.ps1").write_text('''param([switch]$Publish)
@{ publish = [bool]$Publish; window = [Diagnostics.Process]::GetCurrentProcess().MainWindowHandle.ToInt64() } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'background-result.json')
exit 7
''', encoding="utf-8")
            for arguments, publish in (([], False), (["-Publish"], True)):
                with self.subTest(publish=publish):
                    result = subprocess.run(
                        ["wscript.exe", "//B", "//Nologo", str(launcher), *arguments],
                        capture_output=True, timeout=20,
                    )
                    self.assertEqual(result.returncode, 7)
                    data = json.loads((folder / "background-result.json").read_text(encoding="utf-8-sig"))
                    self.assertEqual(data["publish"], publish)
                    self.assertEqual(data["window"], 0)


if __name__ == "__main__":
    unittest.main()
