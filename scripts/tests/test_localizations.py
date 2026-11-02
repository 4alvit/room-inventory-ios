"""Negative checks prove broken catalogs cannot pass the release source gate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_localizations", ROOT / "scripts/verify-localizations.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class LocalizationVerificationTests(unittest.TestCase):
    def test_missing_russian_key_is_not_hidden_by_english_fallback(self):
        with self.assertRaisesRegex(VERIFY.LocalizationError, "missing ru"):
            VERIFY.validate_pair("UI", {"Save": "Save", "Cancel": "Cancel"}, {"Save": "Сохранить"})

    def test_placeholder_type_or_count_mismatch_is_rejected(self):
        for translated in ("Импорт %d", "Импорт %@ из %@"):
            with self.subTest(translated=translated), self.assertRaisesRegex(VERIFY.LocalizationError, "format argument mismatch"):
                VERIFY.validate_pair("UI", {"progress": "Importing %@"}, {"progress": translated})

    def test_duplicate_key_is_rejected_before_dictionary_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "UI.strings"
            path.write_text('"Save" = "Сохранить";\n"Save" = "Другое";\n')
            with self.assertRaisesRegex(VERIFY.LocalizationError, "duplicate key"):
                VERIFY.parse_catalog(path)

    def test_copied_english_is_not_a_russian_translation(self):
        with self.assertRaisesRegex(VERIFY.LocalizationError, "untranslated Russian"):
            VERIFY.validate_pair("UI", {"Save": "Save"}, {"Save": "Save"})

    def test_argument_reordering_preserves_types_and_literal_percent(self):
        VERIFY.validate_pair("UI", {"progress": "%@ uses %lld%%"}, {"progress": "%2$lld%% занимает %1$@"})

    def test_production_catalogs_and_references(self):
        counts = VERIFY.verify(ROOT)
        self.assertEqual(set(counts), {"UI", "Services", "Export", "InfoPlist", "Core"})


if __name__ == "__main__":
    unittest.main()
