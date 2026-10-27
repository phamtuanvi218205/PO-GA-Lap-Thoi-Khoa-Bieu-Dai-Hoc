"""Kiểm thử điểm vào CLI của tầng ứng dụng Python."""

from __future__ import annotations

import json
from pathlib import Path

from gapo_timetabling.application import app_cli
from gapo_timetabling.application.timetable_export import TimetableCsvExportResult


class FakeConnection:
    """Connection tối thiểu để xác nhận CLI luôn đóng tài nguyên."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_export_schedule_command_forwards_filters_and_prints_result(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    connection = FakeConnection()
    captured: dict[str, object] = {}
    query_token = object()
    output = tmp_path / "schedule.csv"

    monkeypatch.setattr(app_cli, "connect_sql_server", lambda: connection)
    monkeypatch.setattr(app_cli, "TimetableQueryService", lambda value: query_token)

    class FakeExportService:
        def __init__(self, query_service: object) -> None:
            assert query_service is query_token

        def export_run_csv(self, run_id, output_path, filters):
            captured.update(
                run_id=run_id,
                output_path=output_path,
                filters=filters,
            )
            return TimetableCsvExportResult(output.resolve(), 2)

    monkeypatch.setattr(app_cli, "TimetableExportService", FakeExportService)

    exit_code = app_cli.main([
        "export-schedule",
        "7",
        "--output",
        str(output),
        "--lecturer-code",
        "GV001",
        "--section-code",
        "JAVA01",
        "--term-code",
        "2026_HK1",
        "--week-number",
        "2",
    ])

    assert exit_code == 0
    assert connection.closed is True
    assert captured["run_id"] == 7
    assert captured["output_path"] == output
    filters = captured["filters"]
    assert filters.lecturer_code == "GV001"
    assert filters.section_code == "JAVA01"
    assert filters.term_code == "2026_HK1"
    assert filters.week_number == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed == {
        "run_id": 7,
        "output": str(output.resolve()),
        "row_count": 2,
    }
