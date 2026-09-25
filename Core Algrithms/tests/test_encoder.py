import unittest
from dataclasses import replace
from datetime import date, time

from gapo_timetabling.encoder import (
    build_option_domains,
    build_options_for_session,
    get_periods_for_block,
    is_resource_unavailable,
    period_ranges_overlap,
    room_can_host_part,
)
from gapo_timetabling.models import (
    AcademicTerm,
    AcademicTermStatus,
    AllowedPeriodBlock,
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    Course,
    CourseSection,
    DateStatus,
    Lecturer,
    LocationType,
    OnlineLocation,
    PartType,
    PlanningScenario,
    PlanningScenarioItem,
    PlanningScenarioStatus,
    ProblemInstance,
    Room,
    RoomType,
    ScenarioScopeType,
    SessionOption,
    SessionType,
    TeachingDate,
    TeachingDurationRule,
    TeachingPart,
    TeachingPlan,
    TeachingPlanStatus,
    TermWeek,
    TimePeriod,
)


class EncoderFixture(unittest.TestCase):
    """Dữ liệu nhỏ dùng chung cho các test encoder."""

    def setUp(self) -> None:
        self.term = AcademicTerm(
            term_code="2026_HK1",
            term_name="Học kỳ 1",
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 23),
            status=AcademicTermStatus.PLANNING,
        )
        self.week = TermWeek(1, date(2026, 8, 17), date(2026, 8, 23))

        # Tuần có một ngày thường, một ngày nghỉ và một ngày học bù được phép.
        self.tuesday = TeachingDate(
            date(2026, 8, 18), 1, 2, DateStatus.NORMAL
        )
        self.wednesday_holiday = TeachingDate(
            date(2026, 8, 19), 1, 3, DateStatus.HOLIDAY
        )
        self.saturday_makeup = TeachingDate(
            date(2026, 8, 22), 1, 6, DateStatus.MAKEUP_ALLOWED
        )

        # Sáu tiết sáng cho phép kiểm tra hai khung 1-3 và 4-6.
        self.time_periods = tuple(
            TimePeriod(
                period_number=number,
                start_time=time(6 + number, 0),
                end_time=time(6 + number, 50),
                session_type=SessionType.MORNING,
            )
            for number in range(1, 7)
        )
        self.allowed_blocks = (
            AllowedPeriodBlock(1, 3),
            AllowedPeriodBlock(4, 3),
        )
        self.duration_rules = (
            TeachingDurationRule(PartType.LECTURE, 3, True),
            TeachingDurationRule(PartType.LECTURE, 6, True),
            TeachingDurationRule(PartType.PRACTICE, 5, True),
            TeachingDurationRule(PartType.PRACTICE, 6, True),
        )

        # Phòng chỉ có 20 chỗ trong khi chỉ tiêu lớp là 60. Encoder vẫn phải
        # giữ phòng vì sức chứa là tiêu chí mềm.
        self.small_lecture_room = Room(
            location_index=0,
            location_id=10,
            location_code="F201",
            location_name="Phòng F201",
            active=True,
            campus_code="CS1",
            room_type=RoomType.LECTURE_ROOM,
            capacity=20,
            equipment_quantities=(("PROJECTOR", 1),),
        )
        self.computer_lab = Room(
            location_index=1,
            location_id=11,
            location_code="LAB01",
            location_name="Phòng máy 01",
            active=True,
            campus_code="CS1",
            room_type=RoomType.COMPUTER_LAB,
            capacity=80,
            equipment_quantities=(("COMPUTER", 80),),
        )
        self.zoom = OnlineLocation(
            location_index=2,
            location_id=12,
            location_code="ZOOM01",
            location_name="Lớp Zoom 01",
            active=True,
            platform_name="Zoom",
        )

        self.lecturers = (
            Lecturer(0, "GV01", "Giảng viên 01", "CS1"),
            Lecturer(1, "GV02", "Giảng viên 02", None),
        )
        self.courses = (
            Course("KTDL", "Khai thác dữ liệu"),
            Course("TTNT", "Trí tuệ nhân tạo"),
        )
        self.sections = (
            CourseSection("KTDL01", "KTDL", "KTDL 01", 60),
            CourseSection("TTNT01", "TTNT", "TTNT 01", None),
        )

        self.physical_part = TeachingPart(
            teaching_part_index=0,
            teaching_part_id=20,
            part_code="KTDL01_LT",
            section_code="KTDL01",
            part_type=PartType.LECTURE,
            lecturer_index=0,
            total_periods=3,
            required_location_type=LocationType.PHYSICAL_ROOM,
            required_room_type=RoomType.LECTURE_ROOM,
            required_equipment=(("PROJECTOR", 1),),
        )
        self.online_part = TeachingPart(
            teaching_part_index=1,
            teaching_part_id=21,
            part_code="TTNT01_LT",
            section_code="TTNT01",
            part_type=PartType.LECTURE,
            lecturer_index=1,
            total_periods=3,
            required_location_type=LocationType.ONLINE,
            required_room_type=None,
        )

        self.physical_plan = TeachingPlan(
            100, "KTDL01_STANDARD", 0, TeachingPlanStatus.APPROVED, False
        )
        self.online_plan = TeachingPlan(
            101, "TTNT01_ONLINE", 1, TeachingPlanStatus.APPROVED, False
        )
        self.physical_session = ClassSession(
            0, 1000, 100, 1, 1, 3, LocationType.PHYSICAL_ROOM
        )
        self.online_session = ClassSession(
            1, 1001, 101, 1, 1, 3, LocationType.ONLINE
        )
        self.scenario = PlanningScenario(
            scenario_id=1,
            scenario_code="SCN_01",
            term_code="2026_HK1",
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.LOCKED,
            items=(
                PlanningScenarioItem(0, 100),
                PlanningScenarioItem(1, 101),
            ),
        )

    def build_problem(
        self,
        *,
        teaching_dates: tuple[TeachingDate, ...] | None = None,
        time_periods: tuple[TimePeriod, ...] | None = None,
        allowed_blocks: tuple[AllowedPeriodBlock, ...] | None = None,
        locations: tuple[Room | OnlineLocation, ...] | None = None,
        lecturer_availabilities: tuple[AvailabilityWindow, ...] = (),
        room_availabilities: tuple[AvailabilityWindow, ...] = (),
    ) -> ProblemInstance:
        """Tạo snapshot hợp lệ; từng test chỉ thay dữ liệu cần kiểm tra."""

        return ProblemInstance(
            term=self.term,
            scenario=self.scenario,
            weeks=(self.week,),
            teaching_dates=teaching_dates or (
                self.tuesday,
                self.wednesday_holiday,
                self.saturday_makeup,
            ),
            time_periods=time_periods or self.time_periods,
            allowed_period_blocks=allowed_blocks or self.allowed_blocks,
            teaching_duration_rules=self.duration_rules,
            locations=locations or (
                self.small_lecture_room,
                self.computer_lab,
                self.zoom,
            ),
            lecturers=self.lecturers,
            courses=self.courses,
            course_sections=self.sections,
            teaching_parts=(self.physical_part, self.online_part),
            teaching_plans=(self.physical_plan, self.online_plan),
            class_sessions=(self.physical_session, self.online_session),
            lecturer_availabilities=lecturer_availabilities,
            room_availabilities=room_availabilities,
            campus_travel_times=(),
            constraint_settings=(),
        )


class TestPeriodRangesOverlap(unittest.TestCase):
    def test_overlapping_ranges_return_true(self) -> None:
        self.assertTrue(period_ranges_overlap(2, 5, 4, 7))

    def test_ranges_touching_one_period_return_true(self) -> None:
        self.assertTrue(period_ranges_overlap(2, 4, 4, 6))

    def test_separate_ranges_return_false(self) -> None:
        self.assertFalse(period_ranges_overlap(1, 3, 4, 6))

    def test_invalid_range_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            period_ranges_overlap(5, 3, 1, 2)


class TestResourceAvailability(unittest.TestCase):
    def setUp(self) -> None:
        self.teaching_date = date(2026, 8, 18)  # Thứ Ba.

    def test_exact_date_unavailable_blocks_resource(self) -> None:
        window = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.teaching_date,
            start_period=2,
            end_period=4,
            availability_type=AvailabilityType.UNAVAILABLE,
        )

        self.assertTrue(
            is_resource_unavailable(
                (window,), 0, self.teaching_date, 3, 5
            )
        )

    def test_weekday_unavailable_repeats_on_matching_weekday(self) -> None:
        window = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )

        self.assertTrue(
            is_resource_unavailable(
                (window,), 0, self.teaching_date, 1, 3
            )
        )

    def test_preferred_window_does_not_block_resource(self) -> None:
        window = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=1.0,
        )

        self.assertFalse(
            is_resource_unavailable(
                (window,), 0, self.teaching_date, 1, 3
            )
        )

    def test_different_date_does_not_block_resource(self) -> None:
        window = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=date(2026, 8, 19),
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )

        self.assertFalse(
            is_resource_unavailable(
                (window,), 0, self.teaching_date, 1, 3
            )
        )


class TestRoomCompatibility(EncoderFixture):
    def test_small_room_remains_valid_because_capacity_is_soft(self) -> None:
        self.assertEqual(self.small_lecture_room.capacity, 20)
        self.assertEqual(self.sections[0].expected_enrollment, 60)
        self.assertTrue(
            room_can_host_part(self.small_lecture_room, self.physical_part)
        )

    def test_inactive_room_is_rejected(self) -> None:
        inactive_room = replace(self.small_lecture_room, active=False)
        self.assertFalse(room_can_host_part(inactive_room, self.physical_part))

    def test_wrong_room_type_is_rejected(self) -> None:
        self.assertFalse(room_can_host_part(self.computer_lab, self.physical_part))

    def test_room_missing_required_equipment_is_rejected(self) -> None:
        room_without_projector = replace(
            self.small_lecture_room,
            equipment_quantities=(),
        )
        self.assertFalse(
            room_can_host_part(room_without_projector, self.physical_part)
        )


class TestAllowedPeriodBlock(EncoderFixture):
    def test_complete_block_returns_all_periods(self) -> None:
        result = get_periods_for_block(
            self.time_periods,
            AllowedPeriodBlock(1, 3),
        )
        self.assertEqual(
            tuple(period.period_number for period in result or ()),
            (1, 2, 3),
        )

    def test_missing_period_invalidates_block(self) -> None:
        periods_without_two = tuple(
            period
            for period in self.time_periods
            if period.period_number != 2
        )
        self.assertIsNone(
            get_periods_for_block(periods_without_two, AllowedPeriodBlock(1, 3))
        )

    def test_block_crossing_session_boundary_is_invalid(self) -> None:
        periods = (
            self.time_periods[0],
            replace(self.time_periods[1], session_type=SessionType.AFTERNOON),
            replace(self.time_periods[2], session_type=SessionType.AFTERNOON),
        )
        self.assertIsNone(
            get_periods_for_block(periods, AllowedPeriodBlock(1, 3))
        )


class TestBuildOptionsForSession(EncoderFixture):
    def test_physical_session_uses_valid_dates_blocks_and_room(self) -> None:
        problem = self.build_problem()

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 4)
        self.assertTrue(
            all(option.location_index == self.small_lecture_room.location_index
                for option in options)
        )
        self.assertEqual(
            {option.teaching_date for option in options},
            {self.tuesday.calendar_date, self.saturday_makeup.calendar_date},
        )
        self.assertNotIn(
            self.wednesday_holiday.calendar_date,
            {option.teaching_date for option in options},
        )

    def test_only_configured_blocks_are_generated(self) -> None:
        problem = self.build_problem()

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(
            {(option.start_period, option.end_period) for option in options},
            {(1, 3), (4, 6)},
        )

    def test_weekday_lecturer_unavailable_removes_only_overlapping_options(self) -> None:
        unavailable = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        problem = self.build_problem(lecturer_availabilities=(unavailable,))

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 3)
        self.assertNotIn(
            SessionOption(0, 0, self.tuesday.calendar_date, 1, 3),
            options,
        )

    def test_exact_date_room_unavailable_removes_only_that_option(self) -> None:
        unavailable = AvailabilityWindow(
            resource_index=self.small_lecture_room.location_index,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=4,
            end_period=6,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        problem = self.build_problem(room_availabilities=(unavailable,))

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 3)
        self.assertNotIn(
            SessionOption(0, 0, self.tuesday.calendar_date, 4, 6),
            options,
        )

    def test_preference_does_not_remove_option(self) -> None:
        preferred = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=6,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=2.0,
        )
        problem = self.build_problem(lecturer_availabilities=(preferred,))

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 4)

    def test_room_discouraged_does_not_remove_option(self) -> None:
        discouraged = AvailabilityWindow(
            resource_index=self.small_lecture_room.location_index,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=6,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=None,
        )
        problem = self.build_problem(room_availabilities=(discouraged,))

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 4)

    def test_online_session_uses_only_active_online_location(self) -> None:
        problem = self.build_problem()

        options = build_options_for_session(problem, self.online_session)

        self.assertEqual(len(options), 4)
        self.assertTrue(
            all(option.location_index == self.zoom.location_index for option in options)
        )

    def test_inactive_online_location_produces_no_online_option(self) -> None:
        inactive_zoom = replace(self.zoom, active=False)
        problem = self.build_problem(
            locations=(
                self.small_lecture_room,
                self.computer_lab,
                inactive_zoom,
            )
        )

        options = build_options_for_session(problem, self.online_session)

        self.assertEqual(options, ())

    def test_missing_time_period_removes_only_affected_block(self) -> None:
        periods_without_two = tuple(
            period
            for period in self.time_periods
            if period.period_number != 2
        )
        problem = self.build_problem(time_periods=periods_without_two)

        options = build_options_for_session(problem, self.physical_session)

        self.assertEqual(len(options), 2)
        self.assertTrue(all(option.start_period == 4 for option in options))

    def test_option_domains_follow_gene_order(self) -> None:
        problem = self.build_problem()

        domains = build_option_domains(problem)

        self.assertEqual(len(domains), problem.dimension)
        self.assertTrue(all(option.session_index == 0 for option in domains[0]))
        self.assertTrue(all(option.session_index == 1 for option in domains[1]))


if __name__ == "__main__":
    unittest.main()
