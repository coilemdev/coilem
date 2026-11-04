"""Display precision for PDF reports, separate from stored and CSV values."""

import math
from typing import Any


def format_report_number(value: Any, decimal_places: int = 3) -> str:
    """At most three decimals; scientific notation keeps small values nonzero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Not recorded"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return "Not recorded"
    if value == 0:
        return "0"
    places = max(0, min(decimal_places, 3))
    if abs(value) < 10 ** -places or abs(value) >= 1e9:
        mantissa, exponent = f"{value:.{places}e}".split("e")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{int(exponent)}"
    text = f"{value:.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
