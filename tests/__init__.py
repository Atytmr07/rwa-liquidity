"""Test suite.

This is a package so that test modules can share fixture builders through
`from .conftest import ...`. Without it, pytest imports each test module
top-level and the shared builders would have to be duplicated or reached through
a sys.path trick.
"""
