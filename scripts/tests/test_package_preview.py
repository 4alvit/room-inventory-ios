"""Publication boundaries are checked without compiling or publishing an app."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest

SPEC = spec_from_file_location("package_preview", Path(__file__).parents[1] / "package-preview.py")
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PreviewPolicyTests(unittest.TestCase):
    def test_rejects_non_candidate_channel_and_unsafe_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VERSION").write_text("0.1.0\n")
            for channel in ("stable", "app-store", "../rc", ""):
                with self.assertRaises(ValueError):
                    MODULE.validate_request("0.1.0", channel, root=root)
            for version in ("../0.1.0", "0.1.1", "v0.1.0", "0.1.0;touch x", "0.1.0-rc.1"):
                with self.assertRaises(ValueError):
                    MODULE.validate_request(version, "rc", root=root)

    def test_accepts_only_committed_base_with_candidate_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VERSION").write_text("0.1.0\n")
            for channel in ("nightly", "beta", "rc"):
                MODULE.validate_request("0.1.0", channel, root=root)


if __name__ == "__main__":
    unittest.main()
