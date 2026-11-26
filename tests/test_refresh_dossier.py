import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh_dossier.py"
spec = importlib.util.spec_from_file_location("refresh_dossier", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DossierTests(unittest.TestCase):
    def test_markers_replace_only_inside_region(self):
        source = "before\n" + module.START + "\nold\n" + module.END + "\nafter"
        result = module.replace_marked_section(source, "new")
        self.assertIn("before\n", result)
        self.assertIn("new", result)
        self.assertTrue(result.endswith("\nafter"))

    def test_missing_markers_fail(self):
        with self.assertRaises(ValueError):
            module.replace_marked_section("no markers", "content")

    def test_duplicate_markers_fail(self):
        source = module.START + module.END + module.START + module.END
        with self.assertRaises(ValueError):
            module.replace_marked_section(source, "content")

    def test_malformed_order_fails(self):
        with self.assertRaises(ValueError):
            module.replace_marked_section(module.END + module.START, "content")

    def test_markdown_text_sanitizes_untrusted_characters(self):
        value = module.markdown_text("A | [B] <C> `D`\\nE", 200)
        self.assertNotIn("|", value)
        self.assertNotIn("[", value)
        self.assertNotIn("]", value)
        self.assertNotIn("<", value)
        self.assertNotIn(">", value)
        self.assertNotIn("`", value)

    def test_missing_description_has_safe_fallback(self):
        repo = {
            "name": "Example",
            "language": None,
            "stargazers_count": 2,
            "pushed_at": "2026-01-01T00:00:00Z",
        }
        card = module.project_card(repo, 1, "Navaneethan-P", 200)
        self.assertIn("No public description supplied.", card)
        self.assertIn("Not specified", card)

    def test_latest_uses_pushed_at_not_updated_at(self):
        config = {"owner": "Navaneethan-P", "featured": [], "excluded": [], "max_description_length": 200}
        repos = [
            {"name": "RepoA", "pushed_at": "2026-01-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z",
             "private": False, "fork": False, "archived": False, "html_url": "https://github.com/Navaneethan-P/RepoA",
             "description": "A", "language": "Python", "stargazers_count": 1},
            {"name": "RepoB", "pushed_at": "2026-02-01T00:00:00Z", "updated_at": "2026-02-01T00:00:00Z",
             "private": False, "fork": False, "archived": False, "html_url": "https://github.com/Navaneethan-P/RepoB",
             "description": "B", "language": "Java", "stargazers_count": 0},
        ]
        with patch.object(module, "get_featured", return_value=[]), \
             patch.object(module, "list_public_repositories", return_value=repos):
            output = module.build_dynamic_section(config)
        self.assertIn("[RepoB]", output)
        self.assertNotIn("[RepoA]", output)

    def test_curated_description_overrides_api_description(self):
        repo = {
            "name": "Phonepad",
            "description": "API description",
            "language": "Python",
            "stargazers_count": 0,
            "pushed_at": "2026-01-01T00:00:00Z",
        }
        curated = {"Phonepad": "Curated Phonepad description"}
        card = module.project_card(repo, 1, "Navaneethan-P", 200, curated)
        self.assertIn("Curated Phonepad description", card)
        self.assertNotIn("API description", card)

    def test_curated_description_used_when_api_description_is_null(self):
        repo = {
            "name": "Phonepad",
            "description": None,
            "language": "Python",
            "stargazers_count": 0,
            "pushed_at": "2026-01-01T00:00:00Z",
        }
        curated = {"Phonepad": "Curated description for null API"}
        card = module.project_card(repo, 1, "Navaneethan-P", 200, curated)
        self.assertIn("Curated description for null API", card)
        self.assertNotIn("No public description supplied.", card)

    def test_latest_signal_uses_curated_description(self):
        config = {
            "owner": "Navaneethan-P",
            "featured": [],
            "excluded": [],
            "descriptions": {"LatestRepo": "Curated latest signal description"},
            "max_description_length": 200,
        }
        repos = [
            {
                "name": "LatestRepo",
                "pushed_at": "2026-03-01T00:00:00Z",
                "private": False,
                "fork": False,
                "archived": False,
                "html_url": "https://github.com/Navaneethan-P/LatestRepo",
                "description": "API latest description",
                "language": "Python",
                "stargazers_count": 1,
            }
        ]
        with patch.object(module, "get_featured", return_value=[]), \
             patch.object(module, "list_public_repositories", return_value=repos):
            output = module.build_dynamic_section(config)
        self.assertIn("Curated latest signal description", output)
        self.assertNotIn("API latest description", output)

    def test_uncurated_repository_uses_api_description(self):
        repo = {
            "name": "UncuratedRepo",
            "description": "Legitimate API description",
            "language": "Go",
            "stargazers_count": 5,
            "pushed_at": "2026-01-01T00:00:00Z",
        }
        curated = {"OtherRepo": "Some other description"}
        card = module.project_card(repo, 1, "Navaneethan-P", 200, curated)
        self.assertIn("Legitimate API description", card)

    def test_empty_curated_description_falls_back_to_api_description(self):
        repo = {
            "name": "FallbackRepo",
            "description": "Original API description",
            "language": "Rust",
            "stargazers_count": 3,
            "pushed_at": "2026-01-01T00:00:00Z",
        }
        for empty_val in ["", "   ", None]:
            curated = {"FallbackRepo": empty_val}
            card = module.project_card(repo, 1, "Navaneethan-P", 200, curated)
            self.assertIn("Original API description", card)

if __name__ == "__main__":
    unittest.main()
