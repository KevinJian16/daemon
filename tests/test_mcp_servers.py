"""Tests for custom MCP servers (import + functionality validation)."""
import json
import pytest
from pathlib import Path


# ── code_functions (tree-sitter) ─────────────────────────────────────────

class TestCodeFunctions:
    def test_extract_python_functions(self):
        from mcp_servers.code_functions import _extract_symbols
        symbols = _extract_symbols("temporal/activities_exec.py")
        names = [s["name"] for s in symbols]
        assert "run_openclaw_step" in names
        assert "run_direct_step" in names

    def test_extract_nested_methods(self):
        from mcp_servers.code_functions import _extract_symbols
        symbols = _extract_symbols("temporal/activities_exec.py")
        nested = [s for s in symbols if "." in s["name"]]
        # run_openclaw_step._emit should be found
        assert any("_emit" in s["name"] for s in nested)

    def test_extract_imports(self):
        from mcp_servers.code_functions import _extract_imports
        imports = _extract_imports("temporal/activities_exec.py")
        assert any("temporalio" in i for i in imports)
        assert any("validate_input" in i for i in imports)

    def test_detect_lang_python(self):
        from mcp_servers.code_functions import _detect_lang
        assert _detect_lang("foo.py") == "python"
        assert _detect_lang("bar.js") == "javascript"
        assert _detect_lang("baz.ts") == "typescript"

    def test_detect_lang_unknown(self):
        from mcp_servers.code_functions import _detect_lang
        assert _detect_lang("readme.md") is None

    def test_extract_empty_for_unknown_lang(self):
        from mcp_servers.code_functions import _extract_symbols
        assert _extract_symbols("README.md") == []

    def test_extract_nonexistent_file(self):
        from mcp_servers.code_functions import _extract_symbols
        assert _extract_symbols("/nonexistent/file.py") == []

    def test_symbol_has_line_numbers(self):
        from mcp_servers.code_functions import _extract_symbols
        symbols = _extract_symbols("temporal/activities_exec.py")
        for s in symbols:
            assert "line" in s
            assert "end_line" in s
            assert s["line"] > 0


# ── semantic_scholar (import validation) ─────────────────────────────────

class TestSemanticScholar:
    def test_imports(self):
        from mcp_servers.semantic_scholar import app
        assert app is not None
        assert app.name == "semantic-scholar"

    def test_headers_no_key(self, monkeypatch):
        monkeypatch.delenv("S2_API_KEY", raising=False)
        from mcp_servers.semantic_scholar import _headers
        h = _headers()
        assert "Accept" in h
        assert "x-api-key" not in h

    def test_headers_with_key(self, monkeypatch):
        monkeypatch.setenv("S2_API_KEY", "test-key-123")
        from mcp_servers.semantic_scholar import _headers
        h = _headers()
        assert h["x-api-key"] == "test-key-123"


# ── paper_tools (import + bibtex validation) ─────────────────────────────

class TestPaperTools:
    def test_imports(self):
        from mcp_servers.paper_tools import app
        assert app is not None
        assert app.name == "paper-tools"

    def test_bibtex_format(self):
        from mcp_servers.paper_tools import _bibtex_format
        result = _bibtex_format({
            "entries": [
                {
                    "type": "article",
                    "key": "smith2024",
                    "title": "Test Paper",
                    "author": "Smith, John",
                    "year": "2024",
                    "journal": "Nature",
                }
            ]
        })
        text = json.loads(result.text)
        assert text["status"] == "ok"
        assert text["entry_count"] == 1
        assert "@article{smith2024," in text["bib_content"]
        assert "title = {Test Paper}" in text["bib_content"]

    def test_bibtex_multiple_entries(self):
        from mcp_servers.paper_tools import _bibtex_format
        result = _bibtex_format({
            "entries": [
                {"type": "article", "key": "a1", "title": "Paper A", "author": "A", "year": "2024"},
                {"type": "inproceedings", "key": "b2", "title": "Paper B", "author": "B", "year": "2023"},
            ]
        })
        text = json.loads(result.text)
        assert text["entry_count"] == 2
        assert "@article{a1," in text["bib_content"]
        assert "@inproceedings{b2," in text["bib_content"]


# ── firecrawl_scrape (import validation) ─────────────────────────────────

class TestFirecrawlScrape:
    def test_imports(self):
        from mcp_servers.firecrawl_scrape import app
        assert app is not None
        assert app.name == "firecrawl-scrape"
