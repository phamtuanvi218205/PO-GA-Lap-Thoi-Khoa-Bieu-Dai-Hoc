"""Kiểm thử việc chọn tuần đại diện cho ảnh thời khóa biểu."""

from __future__ import annotations

import unittest
from datetime import date

from gapo_timetabling.reporting import (
    TimetableReportRow,
    _assign_parallel_lanes,
    _select_representative_week_rows,
)


class RepresentativeWeekSelectionTests(unittest.TestCase):
    """Bảo đảm ảnh chỉ dùng một tuần nhưng chọn tuần có đủ dữ liệu nhất."""

    @staticmethod
    def make_row(week_number: int, day: int, session_index: int) -> TimetableReportRow:
        return TimetableReportRow(
            session_index=session_index,
            week_number=week_number,
            teaching_date=date(2026, 9, day),
            start_period=1,
            end_period=3,
            section_code="JAVA01",
            course_code="JAVA",
            course_name="Lập trình Java",
            part_type="Lý thuyết",
            lecturer_code="GV001",
            lecturer_name="Giảng viên A",
            location_code="A201",
        )

    def test_empty_result_returns_no_representative_week(self) -> None:
        self.assertEqual(_select_representative_week_rows(()), ())

    def test_week_with_most_sessions_is_selected(self) -> None:
        rows = (
            self.make_row(1, 7, 0),
            self.make_row(2, 14, 1),
            self.make_row(2, 15, 2),
        )

        selected = _select_representative_week_rows(rows)

        self.assertEqual(len(selected), 2)
        self.assertEqual({row.week_number for row in selected}, {2})

    def test_earliest_week_wins_when_session_counts_are_equal(self) -> None:
        rows = (
            self.make_row(2, 14, 0),
            self.make_row(1, 7, 1),
        )

        selected = _select_representative_week_rows(rows)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].week_number, 1)

    def test_overlapping_sessions_are_assigned_to_different_lanes(self) -> None:
        rows = (
            self.make_row(1, 7, 0),
            self.make_row(1, 7, 1),
        )

        placements = _assign_parallel_lanes(rows)

        self.assertEqual({lane for _, lane, _ in placements}, {0, 1})
        self.assertEqual({lane_count for _, _, lane_count in placements}, {2})

    def test_non_overlapping_sessions_reuse_the_same_lane(self) -> None:
        first = self.make_row(1, 7, 0)
        second = TimetableReportRow(
            session_index=1,
            week_number=1,
            teaching_date=date(2026, 9, 7),
            start_period=4,
            end_period=6,
            section_code="JAVA02",
            course_code="JAVA",
            course_name="Lập trình Java",
            part_type="Thực hành",
            lecturer_code="GV002",
            lecturer_name="Giảng viên B",
            location_code="LAB-A",
        )

        placements = _assign_parallel_lanes((first, second))

        self.assertEqual(
            [(lane, lane_count) for _, lane, lane_count in placements],
            [(0, 1), (0, 1)],
        )


if __name__ == "__main__":
    unittest.main()
