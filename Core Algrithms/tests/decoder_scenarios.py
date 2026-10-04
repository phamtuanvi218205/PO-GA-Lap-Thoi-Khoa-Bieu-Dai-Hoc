"""Dữ liệu kiểm thử decoder nhiều buổi; không phải dữ liệu HUIT thực tế."""

from dataclasses import replace
from datetime import timedelta

from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.models import (
    DateStatus,
    LocationType,
    ProblemInstance,
    SessionOption,
    TeachingDate,
    TermWeek,
)
from tests.test_constraints import ConstraintFixture


def make_multisession_problem(week_count: int = 3) -> ProblemInstance:
    """Lặp bốn part đã biết qua nhiều tuần, mỗi buổi vẫn là một gene riêng."""

    if week_count < 1:
        raise ValueError("week_count phải lớn hơn hoặc bằng 1.")

    fixture = ConstraintFixture()
    fixture.setUp()

    weeks = []
    teaching_dates = []
    sessions = []
    for week_offset in range(week_count):
        day_offset = timedelta(days=7 * week_offset)
        week_number = week_offset + 1
        weeks.append(
            TermWeek(
                week_number,
                fixture.week.start_date + day_offset,
                fixture.week.end_date + day_offset,
            )
        )
        teaching_dates.append(
            TeachingDate(
                fixture.tuesday.calendar_date + day_offset,
                week_number,
                fixture.tuesday.iso_weekday,
                DateStatus.NORMAL,
            )
        )
        teaching_dates.append(
            TeachingDate(
                fixture.wednesday_holiday.calendar_date + day_offset,
                week_number,
                fixture.wednesday_holiday.iso_weekday,
                DateStatus.HOLIDAY,
            )
        )

        for part_index, original_session in enumerate(fixture.sessions):
            session_index = week_offset * len(fixture.sessions) + part_index
            sessions.append(
                replace(
                    original_session,
                    session_index=session_index,
                    class_session_id=1000 + session_index,
                    session_number=week_number,
                    week_number=week_number,
                )
            )

    return replace(
        fixture.problem,
        term=replace(
            fixture.term,
            end_date=weeks[-1].end_date,
        ),
        weeks=tuple(weeks),
        teaching_dates=tuple(teaching_dates),
        teaching_parts=tuple(
            replace(part, total_periods=3 * week_count)
            for part in fixture.parts
        ),
        class_sessions=tuple(sessions),
    )


def make_stress_domains(
    problem: ProblemInstance,
) -> tuple[tuple[SessionOption, ...], ...]:
    """Giữ option encoder hợp lệ riêng nhưng tạo xung đột ghép lịch.

    Đây là miền tổng hợp có chủ đích để kiểm tra quay lui, không đại diện cho
    phân phối dữ liệu thật. Mỗi tuần có ít nhất hai lịch hợp lệ.
    """

    all_domains = build_option_domains(problem)
    allowed_starts = {
        0: (1, 4),
        1: (4, 7),
        2: (4, 7),
        3: (1, 4, 7),
    }
    domains = []
    for session_index, domain in enumerate(all_domains):
        part_index = session_index % 4
        location_index = 2 if part_index == 3 else 0
        selected = tuple(
            option
            for option in domain
            if option.location_index == location_index
            and option.start_period in allowed_starts[part_index]
        )
        if len(selected) != len(allowed_starts[part_index]):
            raise ValueError("Fixture nhiều buổi không sinh đủ option mong đợi.")
        domains.append(selected)

    return tuple(domains)
