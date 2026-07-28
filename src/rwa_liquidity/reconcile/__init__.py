"""Cross-source variance reporting.

When two providers report different figures for the same asset, the package
reports the disagreement rather than silently choosing a winner. Which source is
correct is a research question, not something a library should decide.
"""
