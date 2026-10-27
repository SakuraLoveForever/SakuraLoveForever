import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codeforces_badge


class CodeforcesBadgeTests(unittest.TestCase):
    def test_refresh_saves_rating_and_preserves_badge_on_upstream_failure(self):
        profile = json.dumps({"status": "OK", "result": [
            {"handle": "Sakura_Love", "maxRating": 1725}
        ]}).encode()
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" aria-label="Codeforces: 1725"><title>Codeforces: 1725</title></svg>'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "codeforces.svg"
            with patch.object(codeforces_badge, "urlopen", side_effect=[io.BytesIO(profile), io.BytesIO(svg)]):
                codeforces_badge.refresh(output)
            self.assertEqual(output.read_bytes(), svg)
            for responses in (
                [OSError("API unavailable")],
                [io.BytesIO(b'{"status":"FAILED"}')],
                [io.BytesIO(profile), io.BytesIO(b'<svg aria-label="Codeforces: inaccessible"/>')],
                [io.BytesIO(profile), io.BytesIO(b'<html>rate limited</html>')],
            ):
                with self.subTest(responses=responses):
                    with patch.object(codeforces_badge, "urlopen", side_effect=responses):
                        with self.assertRaises((OSError, ValueError)):
                            codeforces_badge.refresh(output)
                    self.assertEqual(output.read_bytes(), svg)


if __name__ == "__main__":
    unittest.main()
