import unittest

from slug import slugify


class SlugifyTests(unittest.TestCase):
    def test_collapses_and_trims_whitespace(self) -> None:
        self.assertEqual("hello-world", slugify("  Hello   World  "))

    def test_normalizes_tabs_and_newlines(self) -> None:
        self.assertEqual("hello-world-again", slugify("Hello\tWorld\nAgain"))

    def test_all_whitespace_becomes_empty(self) -> None:
        self.assertEqual("", slugify(" \t\n "))

    def test_preserves_existing_hyphens(self) -> None:
        self.assertEqual("already-valid", slugify("Already-valid"))


if __name__ == "__main__":
    unittest.main()
