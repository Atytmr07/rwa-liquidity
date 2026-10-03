"""Writing results out: CSV, parquet, and LaTeX.

The LaTeX writer is hand-written rather than delegated to `pandas.to_latex`.
That is a deliberate choice: the output of this package is meant for a paper, and
a table going into a paper needs control over column alignment, significant
figures, and the caption. Pulling in pandas to get a table whose formatting then
has to be fought is worse than forty lines that produce exactly what is wanted
and depend on nothing.

pandas therefore stays an optional extra, used only by `to_pandas` for callers
who want a pandas frame back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["to_latex", "to_pandas", "write_frame"]

#: What a `None` becomes in a LaTeX table. An empty cell would look like an
#: oversight; this says the metric was undefined, which is a result.
_LATEX_UNDEFINED: Final = "--"

_LATEX_ESCAPES: Final = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def _escape(text: str) -> str:
    """Escape LaTeX special characters.

    Asset uids contain underscores and source names contain them too, so an
    unescaped table simply fails to compile.
    """
    return "".join(_LATEX_ESCAPES.get(character, character) for character in text)


def _format_cell(value: Any, precision: int) -> str:
    if value is None:
        return _LATEX_UNDEFINED
    if isinstance(value, bool):
        # Before the int branch: bool is a subclass of int, and a count of
        # "1.0000" where "yes" was meant is worse than either.
        return "yes" if value else "no"
    if isinstance(value, int):
        # Counts are counts. Padding them with decimals implies a precision the
        # figure does not have.
        return f"{value:,d}"
    if isinstance(value, float):
        return f"{value:,.{precision}f}"
    return _escape(str(value))


def to_latex(
    frame: pl.DataFrame,
    *,
    caption: str | None = None,
    label: str | None = None,
    precision: int = 4,
    column_labels: Mapping[str, str] | None = None,
) -> str:
    r"""Render `frame` as a LaTeX `tabular` inside a `table` environment.

    Numeric columns are right-aligned, text columns left-aligned. `booktabs`
    rules are used, so the preamble needs `\\usepackage{booktabs}`.

    Args:
        frame: The table to render.
        caption: Caption text, escaped.
        label: Cross-reference label, emitted verbatim.
        precision: Decimal places for numeric cells.
        column_labels: Nicer headings, keyed by column name.

    Returns:
        The LaTeX source.
    """
    labels = dict(column_labels or {})
    headers = [_escape(labels.get(name, name)) for name in frame.columns]
    alignment = "".join("r" if frame.schema[name].is_numeric() else "l" for name in frame.columns)

    lines = ["\\begin{table}[htbp]", "  \\centering"]
    if caption is not None:
        lines.append(f"  \\caption{{{_escape(caption)}}}")
    if label is not None:
        lines.append(f"  \\label{{{label}}}")
    lines += [
        f"  \\begin{{tabular}}{{{alignment}}}",
        "    \\toprule",
        "    " + " & ".join(headers) + r" \\",
        "    \\midrule",
    ]
    for row in frame.iter_rows():
        cells = [_format_cell(value, precision) for value in row]
        lines.append("    " + " & ".join(cells) + r" \\")
    lines += ["    \\bottomrule", "  \\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


def write_frame(
    frame: pl.DataFrame,
    path: Path,
    *,
    fmt: str | None = None,
    caption: str | None = None,
    column_labels: Mapping[str, str] | None = None,
) -> Path:
    """Write `frame` to `path`, choosing the format from the suffix.

    Args:
        frame: The table to write.
        path: Destination. Parent directories are created.
        fmt: Override the format. One of `csv`, `parquet`, `tex`.
        caption: Caption, for LaTeX output.
        column_labels: Nicer headings, for LaTeX output.

    Returns:
        The path written.

    Raises:
        ValueError: If the format is not recognised.
    """
    resolved = (fmt or path.suffix.lstrip(".")).lower()
    path.parent.mkdir(parents=True, exist_ok=True)

    if resolved == "csv":
        frame.write_csv(path)
    elif resolved == "parquet":
        frame.write_parquet(path)
    elif resolved in {"tex", "latex"}:
        path.write_text(
            to_latex(frame, caption=caption, column_labels=column_labels), encoding="utf-8"
        )
    else:
        raise ValueError(f"unknown export format {resolved!r}; use one of csv, parquet, tex")
    return path


def to_pandas(frame: pl.DataFrame) -> Any:
    """Convert to a pandas DataFrame, for callers who want one.

    This is the only place in the package that touches pandas, and it is behind
    the optional `pandas` extra. Everything upstream is polars.

    Raises:
        ImportError: With an actionable message if the extra is not installed.
    """
    try:
        import pandas  # noqa: F401, PLC0415 -- optional extra, imported on use
    except ImportError as error:  # pragma: no cover - depends on the install
        raise ImportError(
            "pandas interop requires the optional extra: `uv sync --extra pandas`. "
            "The package itself is polars-only; pandas exists here for callers who "
            "want a pandas frame back."
        ) from error
    return frame.to_pandas()
