"""Output writers: CSV, parquet, and LaTeX tables.

This is the only place in the package where pandas may appear, and only behind
the optional `pandas` extra. Everything upstream is polars.

The LaTeX writer is hand-written rather than delegated to `pandas.to_latex`,
because a table going into a paper needs control over alignment, significant
figures and caption that would otherwise have to be fought for after the fact.
"""

from rwa_liquidity.export.writers import to_latex, to_pandas, write_frame

__all__ = ["to_latex", "to_pandas", "write_frame"]
