"""Literal text handling for exported spreadsheet cells."""

from typing import Any


def literal_csv_cell(value: Any) -> Any:
    """Prevent text from being evaluated as a spreadsheet formula.

    Keep numeric types numeric, including negative measured quantities.
    """
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value
