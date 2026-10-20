"""CLI máy đọc được cho hợp đồng chạy optimizer thời khóa biểu.

Cách dùng:

``python -m gapo_timetabling.run_cli request.json --result result.json``

CLI không in bảng lịch hoặc biểu đồ. Kết quả chính thức được ghi vào JSON để
Java đọc ổn định; stdout chỉ phát một sự kiện JSON ngắn báo vị trí kết quả.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .run_contract import (
    RESULT_SCHEMA_VERSION,
    RunContractError,
    RunErrorCode,
    build_failure_result,
    execute_run_request,
    load_run_request,
    write_result_json,
)


EXIT_SUCCESS = 0
EXIT_INVALID_REQUEST = 2
EXIT_RUN_FAILED = 3
EXIT_IO_ERROR = 4


def _build_parser() -> argparse.ArgumentParser:
    """Khai báo giao diện tối thiểu, không trộn tham số optimizer vào CLI."""

    parser = argparse.ArgumentParser(
        description="Chạy GA, PO hoặc GA-PO từ optimization-run-request.v1.",
    )
    parser.add_argument("request", type=Path, help="File request JSON.")
    parser.add_argument(
        "--result",
        type=Path,
        required=True,
        help="File optimization-run-result.v1 sẽ được tạo.",
    )
    return parser


def _emit_final_event(result_path: Path, payload: dict) -> None:
    """Phát một dòng JSON để subprocess biết run đã kết thúc."""

    print(json.dumps({
        "schema_version": "optimization-run-event.v1",
        "event": payload["status"],
        "request_id": payload.get("request_id"),
        "result_path": str(result_path.resolve()),
        "error_code": (
            payload["error"]["code"] if payload.get("error") else None
        ),
    }, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    """Đọc request, thực thi run và bảo đảm lỗi cũng có result JSON."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)
    request = None
    try:
        request = load_run_request(args.request)
        payload = execute_run_request(request)
        exit_code = EXIT_SUCCESS if payload["status"] == "COMPLETED" else EXIT_RUN_FAILED
    except RunContractError as error:
        payload = build_failure_result(request, error.code, str(error))
        exit_code = EXIT_INVALID_REQUEST
    except (OSError, TypeError, ValueError) as error:
        payload = build_failure_result(
            request,
            RunErrorCode.INVALID_REQUEST,
            str(error),
        )
        exit_code = EXIT_INVALID_REQUEST

    try:
        write_result_json(args.result, payload)
    except OSError as error:
        emergency = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "FAILED",
            "error": {
                "code": RunErrorCode.IO_ERROR.value,
                "message": str(error),
            },
        }
        print(json.dumps(emergency, ensure_ascii=False), file=sys.stderr)
        return EXIT_IO_ERROR

    _emit_final_event(args.result, payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
