"""Branding contract tests that do not require the API runtime dependencies."""

import unittest
from pathlib import Path


class TestApiBranding(unittest.TestCase):
    def test_openapi_title_uses_current_product_name(self):
        main_source = (Path(__file__).parents[1] / "api" / "main.py").read_text(encoding="utf-8")

        self.assertIn('title="审核智规 API"', main_source)
        self.assertNotIn("保险智答", main_source)


if __name__ == "__main__":
    unittest.main()
