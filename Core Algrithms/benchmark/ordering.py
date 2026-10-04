"""Quy tắc sắp xếp tự nhiên cho tên hàm benchmark có hậu tố số."""

from __future__ import annotations

import re


def function_sort_key(function_name: str) -> tuple[str, int, str]:
    """Đặt F2 trước F10 trong khi vẫn hỗ trợ tên không có hậu tố số."""

    match = re.match(r"^(.*?)(\d+)$", function_name)
    if match is None:
        return function_name, -1, function_name
    return match.group(1), int(match.group(2)), function_name
