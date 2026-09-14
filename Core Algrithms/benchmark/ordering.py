"""Quy tac sap xep ten ham benchmark theo chi so so hoc."""

from __future__ import annotations

import re


def function_sort_key(function_name: str) -> tuple[str, int, str]:
    """Dat F2 truoc F10 trong khi van ho tro ten ham khong co chi so."""

    match = re.match(r"^(.*?)(\d+)$", function_name)
    if match is None:
        return function_name, -1, function_name
    return match.group(1), int(match.group(2)), function_name
