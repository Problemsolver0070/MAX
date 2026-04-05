"""Tests for document tools — PDF, spreadsheet, CSV, and JSON."""

import csv
import json
from unittest.mock import MagicMock, patch

import pytest

from max.tools.native.document_tools import (
    TOOL_DEFINITIONS,
    _parse_page_range,
    handle_document_parse_json,
    handle_document_read_pdf,
    handle_document_read_spreadsheet,
    handle_document_write_csv,
    handle_document_write_spreadsheet,
)

# ── Tool definitions ──────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_five_tools(self):
        assert len(TOOL_DEFINITIONS) == 5

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {
            "document.read_pdf",
            "document.read_spreadsheet",
            "document.write_csv",
            "document.write_spreadsheet",
            "document.parse_json",
        }

    def test_all_document_category(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "document"

    def test_all_native_provider(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native"

    def test_each_has_input_schema(self):
        for tool in TOOL_DEFINITIONS:
            assert "properties" in tool.input_schema
            assert "required" in tool.input_schema


# ── Page range parser ─────────────────────────────────────────────────


class TestParsePageRange:
    def test_single_page(self):
        assert _parse_page_range("3", 10) == [2]  # 0-based

    def test_page_range(self):
        assert _parse_page_range("2-4", 10) == [1, 2, 3]

    def test_range_clamped_to_total(self):
        # Asking for pages 3-20 but only 5 pages exist
        assert _parse_page_range("3-20", 5) == [2, 3, 4]

    def test_out_of_range_single(self):
        assert _parse_page_range("100", 5) == []

    def test_whitespace_stripped(self):
        assert _parse_page_range("  2 ", 5) == [1]


# ── PDF tools (mocked) ───────────────────────────────────────────────


class TestReadPdf:
    @pytest.mark.asyncio
    async def test_reads_all_pages(self):
        mock_page_1 = MagicMock()
        mock_page_1.extract_text.return_value = "Page one text"
        mock_page_2 = MagicMock()
        mock_page_2.extract_text.return_value = "Page two text"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page_1, mock_page_2]

        with (
            patch("max.tools.native.document_tools.HAS_PYPDF2", True),
            patch(
                "max.tools.native.document_tools.PdfReader",
                create=True,
                return_value=mock_reader,
            ),
            patch("max.tools.native.document_tools.Path.exists", return_value=True),
        ):
            result = await handle_document_read_pdf({"path": "/fake/test.pdf"})
            assert result["page_count"] == 2
            assert result["pages_read"] == 2
            assert "Page one text" in result["text"]
            assert "Page two text" in result["text"]

    @pytest.mark.asyncio
    async def test_reads_specific_pages(self):
        pages = [MagicMock() for _ in range(5)]
        for i, p in enumerate(pages):
            p.extract_text.return_value = f"Page {i + 1}"

        mock_reader = MagicMock()
        mock_reader.pages = pages

        with (
            patch("max.tools.native.document_tools.HAS_PYPDF2", True),
            patch(
                "max.tools.native.document_tools.PdfReader",
                create=True,
                return_value=mock_reader,
            ),
            patch("max.tools.native.document_tools.Path.exists", return_value=True),
        ):
            result = await handle_document_read_pdf({"path": "/fake/test.pdf", "pages": "2-3"})
            assert result["page_count"] == 5
            assert result["pages_read"] == 2
            assert "Page 2" in result["text"]
            assert "Page 3" in result["text"]
            assert "Page 1" not in result["text"]

    @pytest.mark.asyncio
    async def test_handles_none_extract_text(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with (
            patch("max.tools.native.document_tools.HAS_PYPDF2", True),
            patch(
                "max.tools.native.document_tools.PdfReader",
                create=True,
                return_value=mock_reader,
            ),
            patch("max.tools.native.document_tools.Path.exists", return_value=True),
        ):
            result = await handle_document_read_pdf({"path": "/fake/test.pdf"})
            assert result["text"] == ""
            assert result["pages_read"] == 1

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        with patch("max.tools.native.document_tools.HAS_PYPDF2", True):
            with pytest.raises(FileNotFoundError):
                await handle_document_read_pdf({"path": "/nonexistent/test.pdf"})

    @pytest.mark.asyncio
    async def test_missing_pypdf2(self):
        with patch("max.tools.native.document_tools.HAS_PYPDF2", False):
            with pytest.raises(RuntimeError, match="PyPDF2 is not installed"):
                await handle_document_read_pdf({"path": "/fake/test.pdf"})


# ── CSV tools (real files) ────────────────────────────────────────────


class TestWriteCsv:
    @pytest.mark.asyncio
    async def test_writes_csv(self, tmp_path):
        out = tmp_path / "output.csv"
        rows = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob", "age": "25"},
        ]
        result = await handle_document_write_csv({"path": str(out), "rows": rows})
        assert result["rows_written"] == 2
        assert result["path"] == str(out)
        assert out.exists()

        # Verify contents
        with open(out, newline="") as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert len(read_rows) == 2
        assert read_rows[0]["name"] == "Alice"
        assert read_rows[1]["age"] == "25"

    @pytest.mark.asyncio
    async def test_writes_with_explicit_columns(self, tmp_path):
        out = tmp_path / "output.csv"
        rows = [{"name": "Alice", "age": "30", "city": "NYC"}]
        result = await handle_document_write_csv(
            {"path": str(out), "rows": rows, "columns": ["name", "age"]}
        )
        assert result["rows_written"] == 1

        with open(out, newline="") as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert list(read_rows[0].keys()) == ["name", "age"]
        assert "city" not in read_rows[0]

    @pytest.mark.asyncio
    async def test_writes_empty_rows(self, tmp_path):
        out = tmp_path / "empty.csv"
        result = await handle_document_write_csv({"path": str(out), "rows": []})
        assert result["rows_written"] == 0
        assert out.read_text() == ""

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "sub" / "dir" / "output.csv"
        rows = [{"x": "1"}]
        result = await handle_document_write_csv({"path": str(out), "rows": rows})
        assert result["rows_written"] == 1
        assert out.exists()


class TestReadSpreadsheetCsv:
    @pytest.mark.asyncio
    async def test_reads_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")

        result = await handle_document_read_spreadsheet({"path": str(csv_file)})
        assert result["columns"] == ["name", "age"]
        assert result["row_count"] == 2
        assert result["rows"][0]["name"] == "Alice"
        assert result["rows"][1]["age"] == "25"

    @pytest.mark.asyncio
    async def test_csv_roundtrip(self, tmp_path):
        """Write CSV then read it back — full roundtrip."""
        csv_file = tmp_path / "roundtrip.csv"
        rows = [
            {"id": "1", "value": "hello"},
            {"id": "2", "value": "world"},
        ]
        await handle_document_write_csv({"path": str(csv_file), "rows": rows})
        result = await handle_document_read_spreadsheet({"path": str(csv_file)})
        assert result["row_count"] == 2
        assert result["rows"][0]["id"] == "1"
        assert result["rows"][1]["value"] == "world"

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_document_read_spreadsheet({"path": str(tmp_path / "nope.csv")})

    @pytest.mark.asyncio
    async def test_unsupported_format(self, tmp_path):
        f = tmp_path / "data.parquet"
        f.write_text("dummy")
        with pytest.raises(ValueError, match="Unsupported file format"):
            await handle_document_read_spreadsheet({"path": str(f)})


# ── Excel tools (mocked) ─────────────────────────────────────────────


class TestReadSpreadsheetExcel:
    @pytest.mark.asyncio
    async def test_reads_excel(self, tmp_path):
        # Create a fake .xlsx file so path.exists() passes
        xlsx = tmp_path / "data.xlsx"
        xlsx.write_text("fake")

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                ("name", "score"),
                ("Alice", 95),
                ("Bob", 88),
            ]
        )

        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.load_workbook", return_value=mock_wb),
        ):
            result = await handle_document_read_spreadsheet({"path": str(xlsx)})
            assert result["columns"] == ["name", "score"]
            assert result["row_count"] == 2
            assert result["rows"][0]["name"] == "Alice"
            assert result["rows"][1]["score"] == 88

    @pytest.mark.asyncio
    async def test_reads_named_sheet(self, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        xlsx.write_text("fake")

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter([("col1",), ("val1",)])

        mock_wb = MagicMock()
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.load_workbook", return_value=mock_wb),
        ):
            result = await handle_document_read_spreadsheet({"path": str(xlsx), "sheet": "MySheet"})
            mock_wb.__getitem__.assert_called_with("MySheet")
            assert result["row_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_excel(self, tmp_path):
        xlsx = tmp_path / "empty.xlsx"
        xlsx.write_text("fake")

        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter([])  # No rows at all

        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.load_workbook", return_value=mock_wb),
        ):
            result = await handle_document_read_spreadsheet({"path": str(xlsx)})
            assert result["rows"] == []
            assert result["columns"] == []
            assert result["row_count"] == 0

    @pytest.mark.asyncio
    async def test_missing_openpyxl_for_excel(self, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        xlsx.write_text("fake")

        with patch("max.tools.native.document_tools.HAS_OPENPYXL", False):
            with pytest.raises(RuntimeError, match="openpyxl is not installed"):
                await handle_document_read_spreadsheet({"path": str(xlsx)})


class TestWriteSpreadsheet:
    @pytest.mark.asyncio
    async def test_writes_excel(self):
        mock_ws = MagicMock()
        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.Workbook", return_value=mock_wb),
        ):
            result = await handle_document_write_spreadsheet(
                {
                    "path": "/tmp/test_out.xlsx",
                    "rows": [
                        {"name": "Alice", "score": 95},
                        {"name": "Bob", "score": 88},
                    ],
                }
            )
            assert result["rows_written"] == 2
            assert result["path"] == "/tmp/test_out.xlsx"

            # Verify header cells were written
            mock_ws.cell.assert_any_call(row=1, column=1, value="name")
            mock_ws.cell.assert_any_call(row=1, column=2, value="score")
            # Verify data cells were written
            mock_ws.cell.assert_any_call(row=2, column=1, value="Alice")
            mock_ws.cell.assert_any_call(row=2, column=2, value=95)
            mock_ws.cell.assert_any_call(row=3, column=1, value="Bob")

            mock_wb.save.assert_called_once_with("/tmp/test_out.xlsx")
            mock_wb.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_writes_with_custom_sheet_name(self):
        mock_ws = MagicMock()
        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.Workbook", return_value=mock_wb),
        ):
            await handle_document_write_spreadsheet(
                {
                    "path": "/tmp/test_out.xlsx",
                    "rows": [{"x": 1}],
                    "sheet": "Results",
                }
            )
            assert mock_ws.title == "Results"

    @pytest.mark.asyncio
    async def test_writes_with_explicit_columns(self):
        mock_ws = MagicMock()
        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.Workbook", return_value=mock_wb),
        ):
            result = await handle_document_write_spreadsheet(
                {
                    "path": "/tmp/test_out.xlsx",
                    "rows": [{"a": 1, "b": 2, "c": 3}],
                    "columns": ["b", "a"],
                }
            )
            assert result["rows_written"] == 1
            # Only b and a columns should be written
            mock_ws.cell.assert_any_call(row=1, column=1, value="b")
            mock_ws.cell.assert_any_call(row=1, column=2, value="a")

    @pytest.mark.asyncio
    async def test_writes_empty_rows(self):
        mock_ws = MagicMock()
        mock_wb = MagicMock()
        mock_wb.active = mock_ws

        with (
            patch("max.tools.native.document_tools.HAS_OPENPYXL", True),
            patch("max.tools.native.document_tools.Workbook", return_value=mock_wb),
        ):
            result = await handle_document_write_spreadsheet(
                {"path": "/tmp/test_out.xlsx", "rows": []}
            )
            assert result["rows_written"] == 0
            mock_wb.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_openpyxl(self):
        with patch("max.tools.native.document_tools.HAS_OPENPYXL", False):
            with pytest.raises(RuntimeError, match="openpyxl is not installed"):
                await handle_document_write_spreadsheet(
                    {"path": "/tmp/test.xlsx", "rows": [{"x": 1}]}
                )


# ── JSON tools (real files) ───────────────────────────────────────────


class TestParseJson:
    @pytest.mark.asyncio
    async def test_parses_json_object(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"name": "Alice", "score": 95}))

        result = await handle_document_parse_json({"path": str(f)})
        assert result["data"]["name"] == "Alice"
        assert result["data"]["score"] == 95

    @pytest.mark.asyncio
    async def test_parses_json_array(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text(json.dumps([1, 2, 3]))

        result = await handle_document_parse_json({"path": str(f)})
        assert result["data"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_nested_json(self, tmp_path):
        data = {"users": [{"name": "Alice"}, {"name": "Bob"}]}
        f = tmp_path / "nested.json"
        f.write_text(json.dumps(data))

        result = await handle_document_parse_json({"path": str(f)})
        assert len(result["data"]["users"]) == 2

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_document_parse_json({"path": str(tmp_path / "nonexistent.json")})

    @pytest.mark.asyncio
    async def test_jsonpath_query(self, tmp_path):
        data = {"store": {"books": [{"title": "A"}, {"title": "B"}]}}
        f = tmp_path / "store.json"
        f.write_text(json.dumps(data))

        mock_match_a = MagicMock()
        mock_match_a.value = {"title": "A"}
        mock_match_b = MagicMock()
        mock_match_b.value = {"title": "B"}

        mock_expr = MagicMock()
        mock_expr.find.return_value = [mock_match_a, mock_match_b]

        with (
            patch("max.tools.native.document_tools.HAS_JSONPATH", True),
            patch(
                "max.tools.native.document_tools.jsonpath_parse",
                create=True,
                return_value=mock_expr,
            ),
        ):
            result = await handle_document_parse_json({"path": str(f), "query": "$.store.books[*]"})
            assert "results" in result
            assert len(result["results"]) == 2
            assert result["results"][0]["title"] == "A"

    @pytest.mark.asyncio
    async def test_missing_jsonpath_dep(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))

        with patch("max.tools.native.document_tools.HAS_JSONPATH", False):
            with pytest.raises(RuntimeError, match="jsonpath-ng is not installed"):
                await handle_document_parse_json({"path": str(f), "query": "$.key"})

    @pytest.mark.asyncio
    async def test_no_query_returns_data(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))

        result = await handle_document_parse_json({"path": str(f)})
        assert "data" in result
        assert "results" not in result
