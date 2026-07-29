"""The committed worked-example notebook.

A notebook is the easiest artifact in a repository to let rot: it keeps its
outputs after the code beneath it changes, so it can display confident, wrong
numbers indefinitely while every other test passes. These checks make that
visible.

They do not re-execute it. Running a notebook in CI needs a kernel and adds
minutes to the build for a document that changes rarely; asserting that the
committed version was executed cleanly, and that the claims it makes still hold,
catches the failure that actually happens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "worked-example.ipynb"


@pytest.fixture(scope="module")
def notebook() -> dict[str, Any]:
    if not NOTEBOOK.is_file():
        pytest.fail(f"{NOTEBOOK} is missing")
    loaded: dict[str, Any] = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return loaded


def code_cells(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def test_notebook_contains_no_errors(notebook: dict[str, Any]) -> None:
    failing = [
        index
        for index, cell in enumerate(code_cells(notebook))
        if any(output.get("output_type") == "error" for output in cell.get("outputs", []))
    ]
    assert not failing, f"code cells raised: {failing}"


def test_every_code_cell_was_executed(notebook: dict[str, Any]) -> None:
    # An unexecuted cell means the committed notebook was edited and not re-run,
    # so the outputs below it describe an earlier version of the code.
    unexecuted = [
        index
        for index, cell in enumerate(code_cells(notebook))
        if cell.get("execution_count") is None
    ]
    assert not unexecuted, f"cells were never run: {unexecuted}"


def test_cells_were_executed_in_order(notebook: dict[str, Any]) -> None:
    # Out-of-order counts mean the notebook was run piecemeal, and its outputs
    # may not be reproducible top to bottom.
    counts = [cell["execution_count"] for cell in code_cells(notebook)]
    assert counts == sorted(counts)


def test_notebook_shows_the_headline_finding() -> None:
    # The point of the document. If the sample data or the mode filter changed
    # and the notebook was not re-run, this catches it.
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "all  turnover = 0.6600" in text
    assert "secondary_only  turnover = 0.0000" in text


def test_notebook_labels_the_data_as_synthetic(notebook: dict[str, Any]) -> None:
    text = " ".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "markdown"
    )
    assert "synthetic" in text.lower()
