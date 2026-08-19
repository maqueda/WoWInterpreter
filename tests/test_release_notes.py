import unittest

from scripts.build_release_notes import (
    build_release_body,
    extract_changelog_section,
    find_previous_stable_tag,
)


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_only_requested_release(self):
        changelog = """# Changelog

## [2.2.2] - 2026-08-20

texto A

## [2.2.1] - 2026-08-19

texto B
"""
        self.assertEqual("texto A", extract_changelog_section(changelog, "2.2.2"))

    def test_preserves_complex_markdown_and_unicode(self):
        expected = """### Fixed
- `code` and "quotes"
- 中文 → español: traducción

Paragraph with $ and emoji 😀."""
        changelog = f"## [3.0.0] - 2027-01-01\n\n{expected}\n\n## [2.2.2] - 2026-08-20\nold\n"
        self.assertEqual(expected, extract_changelog_section(changelog, "3.0.0"))

    def test_missing_version_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "expected version 2.2.2"):
            extract_changelog_section("## [2.2.1] - 2026-08-19\ntext", "2.2.2")

    def test_empty_section_fails_clearly(self):
        changelog = "## [2.2.2] - 2026-08-20\n\n## [2.2.1] - 2026-08-19\ntext\n"
        with self.assertRaisesRegex(ValueError, "version 2.2.2 is empty"):
            extract_changelog_section(changelog, "2.2.2")

    def test_previous_release_content_is_never_absorbed(self):
        changelog = "## [2.2.2] - today\nnew\n## [2.2.1] - yesterday\nSECRET OLD\n"
        result = extract_changelog_section(changelog, "2.2.2")
        self.assertEqual("new", result)
        self.assertNotIn("SECRET OLD", result)

    def test_final_body_reuses_hash_and_adds_compare_link(self):
        sha256 = "ab" * 32
        body = build_release_body(
            "### Fixed\n- Unicode → 中文",
            sha256,
            "WoWInterpreter-2.2.2-Setup.exe",
            "maqueda/WoWInterpreter",
            "v2.2.2",
            "v2.2.1",
        )
        self.assertEqual(1, body.count(sha256))
        self.assertIn("## SHA-256", body)
        self.assertIn("compare/v2.2.1...v2.2.2", body)

    def test_previous_tag_uses_numeric_semver_not_lexical_order(self):
        tags = ["v2.9.0", "v2.10.0", "v2.2.1", "not-a-release", "v3.0.0-rc1"]
        self.assertEqual("v2.10.0", find_previous_stable_tag("v3.0.0", tags))

    def test_compare_link_is_omitted_when_no_previous_stable_tag_exists(self):
        self.assertIsNone(find_previous_stable_tag("v1.0.0", ["experimental"]))
        body = build_release_body(
            "Initial release", "cd" * 32, "Setup.exe", "owner/repo", "v1.0.0"
        )
        self.assertNotIn("Full Changelog", body)


if __name__ == "__main__":
    unittest.main()
