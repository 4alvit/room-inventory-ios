"""Exercise this repository's notes using the actual vendored publisher parser."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import release_control  # noqa: E402


class ReleaseNotesTests(unittest.TestCase):
    def test_current_changelog_is_publishable(self):
        raw = (ROOT / "CHANGELOG.md").read_bytes()
        response = {
            "type": "file", "path": "CHANGELOG.md", "encoding": "base64",
            "content": base64.b64encode(raw).decode(), "size": len(raw),
            "sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest(),
        }
        class FakeGitHub:
            def api(self, endpoint):
                self.endpoint = endpoint
                return response
        policy = json.loads((ROOT / ".release-policy.json").read_text())
        version = (ROOT / "VERSION").read_text().strip()
        with patch.object(release_control, "source_policy_snapshot", return_value={"data": policy}):
            rendered = release_control.release_notes(FakeGitHub(), f"v{version}-beta.1", "a" * 40, "Synthetic test evidence")
        self.assertIn("### Upgrade", rendered)
        self.assertIn("### Security", rendered)
        self.assertIn("Synthetic test evidence", rendered)


if __name__ == "__main__":
    unittest.main()
