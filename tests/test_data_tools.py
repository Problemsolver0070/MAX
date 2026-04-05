"""Tests for data analysis tools (polars-backed)."""

from __future__ import annotations

import json

import pytest

from max.tools.native.data_tools import (
    TOOL_DEFINITIONS,
    _detect_format,
    handle_data_export,
    handle_data_load,
    handle_data_query,
    handle_data_summarize,
    handle_data_transform,
)

# We test with real polars since it is installed.  If it were not available the
# handlers would return an error dict — tested in TestMissingDependency below.
try:
    import polars as pl

    HAS_POLARS = True
except ImportError:
    HAS_POLARS = False


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_csv(tmp_path):
    """Create a sample CSV file with predictable data."""
    path = tmp_path / "data.csv"
    path.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,NYC\n")
    return str(path)


@pytest.fixture()
def sample_json(tmp_path):
    """Create a sample JSON file (row-oriented)."""
    path = tmp_path / "data.json"
    rows = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
        {"name": "Charlie", "age": 35, "city": "NYC"},
    ]
    path.write_text(json.dumps(rows))
    return str(path)


@pytest.fixture()
def sample_parquet(tmp_path):
    """Create a sample Parquet file."""
    if not HAS_POLARS:
        pytest.skip("polars not installed")
    path = tmp_path / "data.parquet"
    df = pl.DataFrame(
        {
            "name": ["Alice", "Bob", "Charlie"],
            "age": [30, 25, 35],
            "city": ["NYC", "LA", "NYC"],
        }
    )
    df.write_parquet(str(path))
    return str(path)


# ── Tool Definitions ─────────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_five_tools(self):
        assert len(TOOL_DEFINITIONS) == 5

    def test_all_data_category(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "data"

    def test_all_native_provider(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native"

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {
            "data.load",
            "data.query",
            "data.summarize",
            "data.transform",
            "data.export",
        }

    def test_all_have_input_schema(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.input_schema["type"] == "object"
            assert "properties" in tool.input_schema

    def test_all_have_descriptions(self):
        for tool in TOOL_DEFINITIONS:
            assert len(tool.description) > 10


# ── Format Detection ─────────────────────────────────────────────────────


class TestFormatDetection:
    def test_csv_extension(self):
        assert _detect_format("data.csv") == "csv"

    def test_json_extension(self):
        assert _detect_format("data.json") == "json"

    def test_jsonl_extension(self):
        assert _detect_format("data.jsonl") == "json"

    def test_parquet_extension(self):
        assert _detect_format("data.parquet") == "parquet"

    def test_pq_extension(self):
        assert _detect_format("data.pq") == "parquet"

    def test_explicit_format_overrides_extension(self):
        assert _detect_format("data.csv", "json") == "json"

    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="Cannot detect format"):
            _detect_format("data.xyz")

    def test_case_insensitive(self):
        assert _detect_format("data.CSV") == "csv"
        assert _detect_format("data.JSON") == "json"


# ── data.load ────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_POLARS, reason="polars not installed")
class TestDataLoad:
    @pytest.mark.asyncio
    async def test_load_csv(self, sample_csv):
        result = await handle_data_load({"path": sample_csv})
        assert "error" not in result
        assert result["columns"] == ["name", "age", "city"]
        assert result["row_count"] == 3
        assert len(result["preview"]) == 3
        assert result["preview"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_load_json(self, sample_json):
        result = await handle_data_load({"path": sample_json})
        assert "error" not in result
        assert result["row_count"] == 3
        assert "name" in result["columns"]

    @pytest.mark.asyncio
    async def test_load_parquet(self, sample_parquet):
        result = await handle_data_load({"path": sample_parquet})
        assert "error" not in result
        assert result["row_count"] == 3
        assert result["columns"] == ["name", "age", "city"]

    @pytest.mark.asyncio
    async def test_load_with_explicit_format(self, sample_csv):
        result = await handle_data_load({"path": sample_csv, "format": "csv"})
        assert "error" not in result
        assert result["row_count"] == 3

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self):
        result = await handle_data_load({"path": "/tmp/no_such_data_file.csv"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_load_unknown_extension(self, tmp_path):
        path = tmp_path / "data.xyz"
        path.write_text("hello")
        result = await handle_data_load({"path": str(path)})
        assert "error" in result
        assert "Cannot detect format" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_max_10_rows(self, tmp_path):
        """Preview should return at most 10 rows even if file has more."""
        path = tmp_path / "big.csv"
        lines = ["id,val"] + [f"{i},{i * 10}" for i in range(50)]
        path.write_text("\n".join(lines) + "\n")
        result = await handle_data_load({"path": str(path)})
        assert result["row_count"] == 50
        assert len(result["preview"]) == 10


# ── data.query ───────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_POLARS, reason="polars not installed")
class TestDataQuery:
    @pytest.mark.asyncio
    async def test_select_all(self, sample_csv):
        result = await handle_data_query(
            {
                "path": sample_csv,
                "query": "SELECT * FROM data",
            }
        )
        assert "error" not in result
        assert result["row_count"] == 3
        assert "name" in result["columns"]

    @pytest.mark.asyncio
    async def test_select_with_where(self, sample_csv):
        result = await handle_data_query(
            {
                "path": sample_csv,
                "query": "SELECT name, age FROM data WHERE city = 'NYC'",
            }
        )
        assert "error" not in result
        assert result["row_count"] == 2
        names = [r["name"] for r in result["rows"]]
        assert "Alice" in names
        assert "Charlie" in names

    @pytest.mark.asyncio
    async def test_select_with_order(self, sample_csv):
        result = await handle_data_query(
            {
                "path": sample_csv,
                "query": "SELECT name FROM data ORDER BY age DESC",
            }
        )
        assert "error" not in result
        assert result["rows"][0]["name"] == "Charlie"

    @pytest.mark.asyncio
    async def test_invalid_sql(self, sample_csv):
        result = await handle_data_query(
            {
                "path": sample_csv,
                "query": "SELECTT * FROMM nowhere",
            }
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_query_nonexistent_file(self):
        result = await handle_data_query(
            {
                "path": "/tmp/no_such_data_file.csv",
                "query": "SELECT * FROM data",
            }
        )
        assert "error" in result


# ── data.summarize ───────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_POLARS, reason="polars not installed")
class TestDataSummarize:
    @pytest.mark.asyncio
    async def test_summarize_csv(self, sample_csv):
        result = await handle_data_summarize({"path": sample_csv})
        assert "error" not in result
        assert "columns" in result
        # Should have stats for each column
        assert "name" in result["columns"]
        assert "age" in result["columns"]
        assert "city" in result["columns"]
        # Age stats should include count
        age_stats = result["columns"]["age"]
        assert "count" in age_stats

    @pytest.mark.asyncio
    async def test_summarize_parquet(self, sample_parquet):
        result = await handle_data_summarize({"path": sample_parquet})
        assert "error" not in result
        assert "age" in result["columns"]

    @pytest.mark.asyncio
    async def test_summarize_nonexistent(self):
        result = await handle_data_summarize({"path": "/tmp/no_such_file.csv"})
        assert "error" in result


# ── data.transform ───────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_POLARS, reason="polars not installed")
class TestDataTransform:
    @pytest.mark.asyncio
    async def test_filter_equals(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "filter", "column": "city", "operator": "==", "value": "NYC"},
                ],
            }
        )
        assert "error" not in result
        assert result["row_count"] == 2
        for row in result["rows"]:
            assert row["city"] == "NYC"

    @pytest.mark.asyncio
    async def test_filter_greater_than(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "filter", "column": "age", "operator": ">", "value": 28},
                ],
            }
        )
        assert "error" not in result
        assert result["row_count"] == 2  # Alice (30) and Charlie (35)

    @pytest.mark.asyncio
    async def test_sort_ascending(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "sort", "column": "age"},
                ],
            }
        )
        assert "error" not in result
        ages = [r["age"] for r in result["rows"]]
        assert ages == sorted(ages)

    @pytest.mark.asyncio
    async def test_sort_descending(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "sort", "column": "age", "descending": True},
                ],
            }
        )
        assert "error" not in result
        ages = [r["age"] for r in result["rows"]]
        assert ages == sorted(ages, reverse=True)

    @pytest.mark.asyncio
    async def test_group_by_with_agg(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "group_by", "columns": ["city"], "agg": {"age": "mean"}},
                ],
            }
        )
        assert "error" not in result
        assert result["row_count"] == 2  # NYC and LA
        assert "city" in result["columns"]
        assert "age" in result["columns"]

    @pytest.mark.asyncio
    async def test_group_by_count(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "group_by", "columns": ["city"], "agg": {"name": "count"}},
                ],
            }
        )
        assert "error" not in result
        # NYC has 2 people, LA has 1
        rows_by_city = {r["city"]: r for r in result["rows"]}
        assert rows_by_city["NYC"]["name"] == 2
        assert rows_by_city["LA"]["name"] == 1

    @pytest.mark.asyncio
    async def test_chained_operations(self, sample_csv):
        """Filter then sort — operations applied sequentially."""
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "filter", "column": "city", "operator": "==", "value": "NYC"},
                    {"op": "sort", "column": "age", "descending": True},
                ],
            }
        )
        assert "error" not in result
        assert result["row_count"] == 2
        assert result["rows"][0]["name"] == "Charlie"  # 35 > 30

    @pytest.mark.asyncio
    async def test_unknown_operation(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [{"op": "pivot"}],
            }
        )
        assert "error" in result
        assert "Unknown operation" in result["error"]

    @pytest.mark.asyncio
    async def test_unsupported_filter_operator(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "filter", "column": "age", "operator": "LIKE", "value": 30},
                ],
            }
        )
        assert "error" in result
        assert "Unsupported filter operator" in result["error"]

    @pytest.mark.asyncio
    async def test_unsupported_agg_function(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "group_by", "columns": ["city"], "agg": {"age": "median"}},
                ],
            }
        )
        assert "error" in result
        assert "Unsupported aggregation" in result["error"]

    @pytest.mark.asyncio
    async def test_group_by_without_agg(self, sample_csv):
        result = await handle_data_transform(
            {
                "path": sample_csv,
                "operations": [
                    {"op": "group_by", "columns": ["city"]},
                ],
            }
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_transform_nonexistent_file(self):
        result = await handle_data_transform(
            {
                "path": "/tmp/no_such_file.csv",
                "operations": [{"op": "sort", "column": "x"}],
            }
        )
        assert "error" in result


# ── data.export ──────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_POLARS, reason="polars not installed")
class TestDataExport:
    @pytest.mark.asyncio
    async def test_csv_to_json(self, sample_csv, tmp_path):
        output = str(tmp_path / "output.json")
        result = await handle_data_export(
            {
                "input_path": sample_csv,
                "output_path": output,
            }
        )
        assert "error" not in result
        assert result["path"] == output
        assert result["row_count"] == 3
        # Verify output is valid JSON
        import json

        data = json.loads(open(output).read())
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_csv_to_parquet(self, sample_csv, tmp_path):
        output = str(tmp_path / "output.parquet")
        result = await handle_data_export(
            {
                "input_path": sample_csv,
                "output_path": output,
            }
        )
        assert "error" not in result
        assert result["row_count"] == 3
        # Verify we can read the parquet back
        df = pl.read_parquet(output)
        assert len(df) == 3

    @pytest.mark.asyncio
    async def test_parquet_to_csv(self, sample_parquet, tmp_path):
        output = str(tmp_path / "output.csv")
        result = await handle_data_export(
            {
                "input_path": sample_parquet,
                "output_path": output,
            }
        )
        assert "error" not in result
        assert result["row_count"] == 3

    @pytest.mark.asyncio
    async def test_export_with_explicit_format(self, sample_csv, tmp_path):
        output = str(tmp_path / "output.dat")
        result = await handle_data_export(
            {
                "input_path": sample_csv,
                "output_path": output,
                "format": "csv",
            }
        )
        assert "error" not in result
        assert result["row_count"] == 3

    @pytest.mark.asyncio
    async def test_export_nonexistent_input(self, tmp_path):
        output = str(tmp_path / "output.csv")
        result = await handle_data_export(
            {
                "input_path": "/tmp/no_such_file.csv",
                "output_path": output,
            }
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_unknown_output_format(self, sample_csv, tmp_path):
        output = str(tmp_path / "output.xyz")
        result = await handle_data_export(
            {
                "input_path": sample_csv,
                "output_path": output,
            }
        )
        assert "error" in result
        assert "Cannot detect format" in result["error"]


# ── Missing dependency ───────────────────────────────────────────────────


class TestMissingDependency:
    """Verify all handlers gracefully handle missing polars."""

    @pytest.mark.asyncio
    async def test_load_missing_polars(self, monkeypatch):
        import max.tools.native.data_tools as mod

        monkeypatch.setattr(mod, "HAS_POLARS", False)
        result = await handle_data_load({"path": "data.csv"})
        assert "error" in result
        assert "polars" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_query_missing_polars(self, monkeypatch):
        import max.tools.native.data_tools as mod

        monkeypatch.setattr(mod, "HAS_POLARS", False)
        result = await handle_data_query({"path": "data.csv", "query": "SELECT *"})
        assert "error" in result
        assert "polars" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_summarize_missing_polars(self, monkeypatch):
        import max.tools.native.data_tools as mod

        monkeypatch.setattr(mod, "HAS_POLARS", False)
        result = await handle_data_summarize({"path": "data.csv"})
        assert "error" in result
        assert "polars" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_transform_missing_polars(self, monkeypatch):
        import max.tools.native.data_tools as mod

        monkeypatch.setattr(mod, "HAS_POLARS", False)
        result = await handle_data_transform({"path": "data.csv", "operations": []})
        assert "error" in result
        assert "polars" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_export_missing_polars(self, monkeypatch):
        import max.tools.native.data_tools as mod

        monkeypatch.setattr(mod, "HAS_POLARS", False)
        result = await handle_data_export(
            {
                "input_path": "data.csv",
                "output_path": "out.json",
            }
        )
        assert "error" in result
        assert "polars" in result["error"].lower()
