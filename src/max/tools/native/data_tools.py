"""Data analysis tools — load, query, summarize, transform, export (polars-backed)."""

from __future__ import annotations

import asyncio
import operator
from pathlib import Path
from typing import Any

from max.tools.registry import ToolDefinition

try:
    import polars as pl

    HAS_POLARS = True
except ImportError:
    HAS_POLARS = False

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="data.load",
        category="data",
        description="Load a data file (CSV/JSON/Parquet) with columns, count, and preview.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the data file"},
                "format": {
                    "type": "string",
                    "enum": ["csv", "json", "parquet"],
                    "description": "File format. Auto-detected from extension if not provided.",
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="data.query",
        category="data",
        description="Run a SQL query against a data file (table name is 'data').",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the data file"},
                "query": {
                    "type": "string",
                    "description": "SQL query to execute (table name is 'data')",
                },
            },
            "required": ["path", "query"],
        },
    ),
    ToolDefinition(
        tool_id="data.summarize",
        category="data",
        description="Generate statistical summary for all columns in a data file.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the data file"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="data.transform",
        category="data",
        description="Apply transformations (filter, sort, group_by) to a data file.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the data file"},
                "operations": {
                    "type": "array",
                    "description": "List of operations to apply sequentially",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["filter", "sort", "group_by"],
                                "description": "Operation type",
                            },
                            "column": {
                                "type": "string",
                                "description": "Column name (for filter/sort)",
                            },
                            "columns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Column names (for group_by)",
                            },
                            "operator": {
                                "type": "string",
                                "enum": ["==", "!=", ">", "<", ">=", "<="],
                                "description": "Comparison operator (for filter)",
                            },
                            "value": {
                                "description": "Comparison value (for filter)",
                            },
                            "descending": {
                                "type": "boolean",
                                "description": "Sort descending (default false, for sort)",
                            },
                            "agg": {
                                "type": "object",
                                "description": "Aggregation mapping {col: func} for group_by. "
                                "Functions: sum, mean, min, max, count, first, last.",
                            },
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["path", "operations"],
        },
    ),
    ToolDefinition(
        tool_id="data.export",
        category="data",
        description="Load a data file and export it to a different format (CSV, JSON, Parquet).",
        permissions=["fs.read", "fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to the source data file",
                },
                "output_path": {
                    "type": "string",
                    "description": "Path to write the output file",
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "json", "parquet"],
                    "description": "Output format. Auto-detected from extension if omitted.",
                },
            },
            "required": ["input_path", "output_path"],
        },
    ),
]


# ── Helpers ──────────────────────────────────────────────────────────────


def _missing_dep_error() -> dict[str, Any]:
    """Return a standard error when polars is not installed."""
    return {
        "error": "polars is not installed. Install it with: pip install polars",
    }


def _detect_format(path: str, explicit_format: str | None = None) -> str:
    """Detect file format from extension or explicit override."""
    if explicit_format:
        return explicit_format.lower()
    suffix = Path(path).suffix.lower()
    format_map = {
        ".csv": "csv",
        ".json": "json",
        ".jsonl": "json",
        ".ndjson": "json",
        ".parquet": "parquet",
        ".pq": "parquet",
    }
    fmt = format_map.get(suffix)
    if fmt is None:
        raise ValueError(
            f"Cannot detect format from extension '{suffix}'. Specify format explicitly."
        )
    return fmt


def _read_file(path: str, fmt: str) -> pl.DataFrame:
    """Read a data file into a polars DataFrame."""
    readers = {
        "csv": pl.read_csv,
        "json": pl.read_json,
        "parquet": pl.read_parquet,
    }
    reader = readers.get(fmt)
    if reader is None:
        raise ValueError(f"Unsupported format: {fmt}")
    return reader(path)


def _write_file(df: pl.DataFrame, path: str, fmt: str) -> None:
    """Write a polars DataFrame to a file."""
    writers = {
        "csv": df.write_csv,
        "json": df.write_json,
        "parquet": df.write_parquet,
    }
    writer = writers.get(fmt)
    if writer is None:
        raise ValueError(f"Unsupported format: {fmt}")
    writer(path)


_FILTER_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}

_AGG_FUNCS = {
    "sum": "sum",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "count": "count",
    "first": "first",
    "last": "last",
}


# ── Handlers ─────────────────────────────────────────────────────────────


async def handle_data_load(inputs: dict[str, Any]) -> dict[str, Any]:
    """Load a data file and return metadata + preview."""
    if not HAS_POLARS:
        return _missing_dep_error()

    path = inputs["path"]
    explicit_fmt = inputs.get("format")

    def _load() -> dict[str, Any]:
        fmt = _detect_format(path, explicit_fmt)
        df = _read_file(path, fmt)
        return {
            "columns": df.columns,
            "row_count": len(df),
            "preview": df.head(10).to_dicts(),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _load)
    except Exception as exc:
        return {"error": str(exc)}


async def handle_data_query(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run a SQL query against a data file."""
    if not HAS_POLARS:
        return _missing_dep_error()

    path = inputs["path"]
    query = inputs["query"]

    def _query() -> dict[str, Any]:
        fmt = _detect_format(path)
        df = _read_file(path, fmt)
        ctx = pl.SQLContext(data=df)
        result_df = ctx.execute(query).collect()
        return {
            "columns": result_df.columns,
            "rows": result_df.to_dicts(),
            "row_count": len(result_df),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _query)
    except Exception as exc:
        return {"error": str(exc)}


async def handle_data_summarize(inputs: dict[str, Any]) -> dict[str, Any]:
    """Generate statistical summary of a data file."""
    if not HAS_POLARS:
        return _missing_dep_error()

    path = inputs["path"]

    def _summarize() -> dict[str, Any]:
        fmt = _detect_format(path)
        df = _read_file(path, fmt)
        desc = df.describe()

        # Convert describe() output to {column_name: {statistic: value, ...}} format.
        # describe() returns a DataFrame with a "statistic" column and one column per
        # original column.
        stat_col = desc.get_column("statistic").to_list()
        columns: dict[str, dict[str, Any]] = {}
        for col_name in df.columns:
            col_values = desc.get_column(col_name).to_list()
            columns[col_name] = dict(zip(stat_col, col_values))

        return {"columns": columns}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _summarize)
    except Exception as exc:
        return {"error": str(exc)}


async def handle_data_transform(inputs: dict[str, Any]) -> dict[str, Any]:
    """Apply sequential transformation operations to a data file."""
    if not HAS_POLARS:
        return _missing_dep_error()

    path = inputs["path"]
    operations = inputs["operations"]

    def _transform() -> dict[str, Any]:
        fmt = _detect_format(path)
        df = _read_file(path, fmt)

        for op_spec in operations:
            op_type = op_spec["op"]
            if op_type == "filter":
                col = op_spec["column"]
                op_str = op_spec["operator"]
                value = op_spec["value"]
                op_func = _FILTER_OPS.get(op_str)
                if op_func is None:
                    return {"error": f"Unsupported filter operator: {op_str}"}
                df = df.filter(op_func(pl.col(col), value))

            elif op_type == "sort":
                col = op_spec["column"]
                descending = op_spec.get("descending", False)
                df = df.sort(col, descending=descending)

            elif op_type == "group_by":
                group_cols = op_spec["columns"]
                agg_spec = op_spec.get("agg", {})
                agg_exprs = []
                for agg_col, func_name in agg_spec.items():
                    func = _AGG_FUNCS.get(func_name)
                    if func is None:
                        return {"error": f"Unsupported aggregation function: {func_name}"}
                    agg_exprs.append(getattr(pl.col(agg_col), func)())
                if not agg_exprs:
                    return {"error": "group_by requires at least one aggregation in 'agg'"}
                df = df.group_by(group_cols).agg(agg_exprs)

            else:
                return {"error": f"Unknown operation: {op_type}"}

        return {
            "columns": df.columns,
            "rows": df.to_dicts(),
            "row_count": len(df),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _transform)
    except Exception as exc:
        return {"error": str(exc)}


async def handle_data_export(inputs: dict[str, Any]) -> dict[str, Any]:
    """Load a data file and export it to a different format."""
    if not HAS_POLARS:
        return _missing_dep_error()

    input_path = inputs["input_path"]
    output_path = inputs["output_path"]
    explicit_fmt = inputs.get("format")

    def _export() -> dict[str, Any]:
        in_fmt = _detect_format(input_path)
        out_fmt = _detect_format(output_path, explicit_fmt)
        df = _read_file(input_path, in_fmt)
        _write_file(df, output_path, out_fmt)
        return {
            "path": output_path,
            "row_count": len(df),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _export)
    except Exception as exc:
        return {"error": str(exc)}
