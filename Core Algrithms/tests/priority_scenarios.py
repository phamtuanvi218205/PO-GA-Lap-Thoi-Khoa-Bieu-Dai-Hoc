"""Fixture priority có nhánh cụt thật để kiểm tra repair và bộ đếm FE."""

from dataclasses import replace

from gapo_timetabling.core.models import (
    AvailabilityScopeType, AvailabilityType, AvailabilityWindow, SessionOption,
)


def make_priority_repair_case(fixture):
    """Ưu tiên khối 0 trước chọn tiết sớm nhất nhưng chặn hai khối còn lại.

    Ngân sách bốn node không đủ quay lui. Lưới repair thử hai khóa, lần hai
    đưa khối 0 sau khối 1 nên dựng được lịch đúng trong bốn node.
    """
    problem = replace(
        fixture.problem,
        teaching_parts=(fixture.parts[0], fixture.parts[1],
                        replace(fixture.parts[2], lecturer_index=0), fixture.parts[3]),
        lecturer_availabilities=(AvailabilityWindow(
            resource_index=0, scope_type=AvailabilityScopeType.DATE,
            calendar_date=fixture.tuesday.calendar_date,
            start_period=4, end_period=6,
            availability_type=AvailabilityType.PREFERRED, preference_weight=1.0,
        ),),
    )
    domains = (
        (SessionOption(0, 0, fixture.tuesday.calendar_date, 1, 3),
         SessionOption(0, 0, fixture.tuesday.calendar_date, 7, 9)),
        (SessionOption(1, 0, fixture.tuesday.calendar_date, 1, 3),
         SessionOption(1, 0, fixture.tuesday.calendar_date, 4, 6)),
        (SessionOption(2, 0, fixture.tuesday.calendar_date, 1, 3),
         SessionOption(2, 0, fixture.tuesday.calendar_date, 4, 6)),
        (fixture.valid_options[3],),
    )
    return problem, domains, (0.0, 0.25, 0.75, 1.0)
