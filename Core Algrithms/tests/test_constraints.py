import unittest
from dataclasses import replace
from datetime import date, time

from gapo_timetabling.constraints import (
    HardViolationCode,
    validate_timetable,
)
from gapo_timetabling.models import (
    AcademicTerm,
    AcademicTermStatus,
    AllowedPeriodBlock,
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    CampusTravelTime,
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


class ConstraintFixture(unittest.TestCase):
    """Bài toán nhỏ đủ để kiểm tra các xung đột hard của validator."""

    def setUp(self) -> None:
        self.term = AcademicTerm(
            "2026_HK1",
            "Học kỳ 1",
            date(2026, 8, 17),
            date(2026, 8, 23),
            AcademicTermStatus.PLANNING,
        )
        self.week = TermWeek(1, date(2026, 8, 17), date(2026, 8, 23))
        self.tuesday = TeachingDate(
            date(2026, 8, 18), 1, 2, DateStatus.NORMAL
        )
        self.wednesday_holiday = TeachingDate(
            date(2026, 8, 19), 1, 3, DateStatus.HOLIDAY
        )

        # Mỗi tiết dài 50 phút. Giữa tiết 3 và 4 không có thời gian di chuyển,
        # còn khoảng từ tiết 3 đến tiết 7 đủ lớn cho hành trình 45 phút.
        period_times = (
            (1, time(7, 0), time(7, 50)),
            (2, time(8, 0), time(8, 50)),
            (3, time(9, 0), time(9, 50)),
            (4, time(9, 50), time(10, 40)),
            (5, time(10, 50), time(11, 40)),
            (6, time(11, 50), time(12, 40)),
            (7, time(13, 30), time(14, 20)),
            (8, time(14, 30), time(15, 20)),
            (9, time(15, 30), time(16, 20)),
        )
        self.time_periods = tuple(
            TimePeriod(number, start, end, SessionType.MORNING)
            for number, start, end in period_times
        )
        self.allowed_blocks = (
            AllowedPeriodBlock(1, 3),
            AllowedPeriodBlock(4, 3),
            AllowedPeriodBlock(7, 3),
        )

        self.room_cs1 = Room(
            location_index=0,
            location_id=10,
            location_code="F201",
            location_name="Phòng F201",
            active=True,
            campus_code="CS1",
            room_type=RoomType.LECTURE_ROOM,
            capacity=10,
            equipment_quantities=(("PROJECTOR", 1),),
        )
        self.room_cs2 = Room(
            location_index=1,
            location_id=11,
            location_code="B304",
            location_name="Phòng B304",
            active=True,
            campus_code="CS2",
            room_type=RoomType.LECTURE_ROOM,
            capacity=80,
            equipment_quantities=(("PROJECTOR", 1),),
        )
        self.zoom = OnlineLocation(
            location_index=2,
            location_id=12,
            location_code="ZOOM01",
            location_name="Zoom 01",
            active=True,
            platform_name="Zoom",
        )

        self.lecturers = (
            Lecturer(0, "GV01", "Giảng viên 01", "CS1"),
            Lecturer(1, "GV02", "Giảng viên 02", "CS1"),
            Lecturer(2, "GV03", "Giảng viên 03", None),
        )
        self.courses = (Course("KTDL", "Khai thác dữ liệu"),)
        self.sections = tuple(
            CourseSection(f"KTDL0{number}", "KTDL", f"KTDL 0{number}", 60)
            for number in range(1, 5)
        )

        # Hai part đầu cùng giảng viên để kiểm tra trùng lịch và di chuyển.
        # Part thứ ba dùng giảng viên khác để tách riêng lỗi trùng phòng.
        self.parts = (
            self._physical_part(0, 20, "P0", "KTDL01", 0),
            self._physical_part(1, 21, "P1", "KTDL02", 0),
            self._physical_part(2, 22, "P2", "KTDL03", 1),
            TeachingPart(
                teaching_part_index=3,
                teaching_part_id=23,
                part_code="P3",
                section_code="KTDL04",
                part_type=PartType.LECTURE,
                lecturer_index=2,
                total_periods=3,
                required_location_type=LocationType.ONLINE,
                required_room_type=None,
            ),
        )
        self.plans = tuple(
            TeachingPlan(
                teaching_plan_id=100 + index,
                plan_code=f"PLAN_{index}",
                teaching_part_index=index,
                status=TeachingPlanStatus.APPROVED,
                allows_intensive=False,
            )
            for index in range(4)
        )
        self.sessions = (
            ClassSession(0, 1000, 100, 1, 1, 3, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1001, 101, 1, 1, 3, LocationType.PHYSICAL_ROOM),
            ClassSession(2, 1002, 102, 1, 1, 3, LocationType.PHYSICAL_ROOM),
            ClassSession(3, 1003, 103, 1, 1, 3, LocationType.ONLINE),
        )
        self.scenario = PlanningScenario(
            scenario_id=1,
            scenario_code="SCN_01",
            term_code="2026_HK1",
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.LOCKED,
            items=tuple(
                PlanningScenarioItem(index, 100 + index)
                for index in range(4)
            ),
        )

        self.problem = self.build_problem()

        # Lịch cơ sở hợp lệ. Phòng F201 chỉ có 10 chỗ cho lớp dự kiến 60,
        # nhưng capacity là mềm nên validator không được báo lỗi.
        self.valid_options = (
            SessionOption(0, 0, self.tuesday.calendar_date, 1, 3),
            SessionOption(1, 1, self.tuesday.calendar_date, 7, 9),
            SessionOption(2, 0, self.tuesday.calendar_date, 4, 6),
            SessionOption(3, 2, self.tuesday.calendar_date, 1, 3),
        )

    def _physical_part(
        self,
        part_index: int,
        part_id: int,
        part_code: str,
        section_code: str,
        lecturer_index: int,
    ) -> TeachingPart:
        return TeachingPart(
            teaching_part_index=part_index,
            teaching_part_id=part_id,
            part_code=part_code,
            section_code=section_code,
            part_type=PartType.LECTURE,
            lecturer_index=lecturer_index,
            total_periods=3,
            required_location_type=LocationType.PHYSICAL_ROOM,
            required_room_type=RoomType.LECTURE_ROOM,
            required_equipment=(("PROJECTOR", 1),),
        )

    def build_problem(
        self,
        *,
        lecturer_availabilities: tuple[AvailabilityWindow, ...] = (),
        room_availabilities: tuple[AvailabilityWindow, ...] = (),
        travel_times: tuple[CampusTravelTime, ...] | None = None,
        locations: tuple[Room | OnlineLocation, ...] | None = None,
    ) -> ProblemInstance:
        if travel_times is None:
            travel_times = (
                CampusTravelTime("CS1", "CS2", 45),
                CampusTravelTime("CS2", "CS1", 45),
            )

        return ProblemInstance(
            term=self.term,
            scenario=self.scenario,
            weeks=(self.week,),
            teaching_dates=(self.tuesday, self.wednesday_holiday),
            time_periods=self.time_periods,
            allowed_period_blocks=self.allowed_blocks,
            teaching_duration_rules=(
                TeachingDurationRule(PartType.LECTURE, 3, True),
            ),
            locations=locations or (self.room_cs1, self.room_cs2, self.zoom),
            lecturers=self.lecturers,
            courses=self.courses,
            course_sections=self.sections,
            teaching_parts=self.parts,
            teaching_plans=self.plans,
            class_sessions=self.sessions,
            lecturer_availabilities=lecturer_availabilities,
            room_availabilities=room_availabilities,
            campus_travel_times=travel_times,
            constraint_settings=(),
        )

    @staticmethod
    def violation_codes(result) -> set[HardViolationCode]:
        return {violation.code for violation in result.violations}


class TestTimetableValidator(ConstraintFixture):
    def test_valid_timetable_has_no_hard_violations(self) -> None:
        result = validate_timetable(self.problem, self.valid_options)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.violations, ())

    def test_soft_room_capacity_does_not_make_schedule_invalid(self) -> None:
        self.assertEqual(self.room_cs1.capacity, 10)
        self.assertEqual(self.sections[0].expected_enrollment, 60)

        result = validate_timetable(self.problem, self.valid_options)

        self.assertTrue(result.is_valid)

    def test_missing_assignment_is_reported(self) -> None:
        result = validate_timetable(self.problem, self.valid_options[:-1])

        self.assertIn(
            HardViolationCode.MISSING_ASSIGNMENT,
            self.violation_codes(result),
        )

    def test_duplicate_assignment_is_reported(self) -> None:
        duplicated = self.valid_options + (self.valid_options[0],)

        result = validate_timetable(self.problem, duplicated)

        self.assertIn(
            HardViolationCode.DUPLICATE_ASSIGNMENT,
            self.violation_codes(result),
        )

    def test_unknown_session_is_reported(self) -> None:
        unknown_option = SessionOption(
            99, 0, self.tuesday.calendar_date, 1, 3
        )

        result = validate_timetable(
            self.problem,
            self.valid_options + (unknown_option,),
        )

        self.assertIn(
            HardViolationCode.UNKNOWN_SESSION,
            self.violation_codes(result),
        )

    def test_holiday_is_not_allowed(self) -> None:
        options = list(self.valid_options)
        options[0] = replace(
            options[0],
            teaching_date=self.wednesday_holiday.calendar_date,
        )

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.DATE_NOT_ALLOWED,
            self.violation_codes(result),
        )

    def test_wrong_period_range_is_not_allowed(self) -> None:
        options = list(self.valid_options)
        options[0] = replace(options[0], start_period=2, end_period=4)

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.PERIOD_NOT_ALLOWED,
            self.violation_codes(result),
        )

    def test_physical_session_cannot_use_online_location(self) -> None:
        options = list(self.valid_options)
        options[0] = replace(options[0], location_index=self.zoom.location_index)

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.LOCATION_NOT_ALLOWED,
            self.violation_codes(result),
        )

    def test_unavailable_lecturer_is_reported(self) -> None:
        unavailable = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        problem = self.build_problem(lecturer_availabilities=(unavailable,))

        result = validate_timetable(problem, self.valid_options)

        self.assertIn(
            HardViolationCode.LECTURER_UNAVAILABLE,
            self.violation_codes(result),
        )

    def test_unavailable_room_is_reported(self) -> None:
        unavailable = AvailabilityWindow(
            resource_index=self.room_cs1.location_index,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        problem = self.build_problem(room_availabilities=(unavailable,))

        result = validate_timetable(problem, self.valid_options)

        self.assertIn(
            HardViolationCode.ROOM_UNAVAILABLE,
            self.violation_codes(result),
        )

    def test_same_lecturer_cannot_teach_overlapping_sessions(self) -> None:
        options = list(self.valid_options)
        options[1] = replace(options[1], start_period=1, end_period=3)

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.LECTURER_CONFLICT,
            self.violation_codes(result),
        )

    def test_same_physical_room_cannot_host_overlapping_sessions(self) -> None:
        options = list(self.valid_options)
        options[2] = replace(options[2], start_period=1, end_period=3)

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.ROOM_CONFLICT,
            self.violation_codes(result),
        )

    def test_online_location_is_not_treated_as_a_physical_room(self) -> None:
        # Chuyển session 2 thành một buổi online. Hai buổi online của hai
        # giảng viên khác nhau được phép dùng cùng mã Zoom trong cùng giờ vì
        # domain hiện tại không xem OnlineLocation là một phòng vật lý.
        online_part = replace(
            self.parts[2],
            required_location_type=LocationType.ONLINE,
            required_room_type=None,
            required_equipment=(),
        )
        online_session = replace(
            self.sessions[2],
            required_location_type=LocationType.ONLINE,
        )
        problem = replace(
            self.problem,
            teaching_parts=(
                self.parts[0],
                self.parts[1],
                online_part,
                self.parts[3],
            ),
            class_sessions=(
                self.sessions[0],
                self.sessions[1],
                online_session,
                self.sessions[3],
            ),
        )
        options = list(self.valid_options)
        options[2] = SessionOption(
            session_index=2,
            location_index=self.zoom.location_index,
            teaching_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=3,
        )

        result = validate_timetable(problem, tuple(options))

        self.assertTrue(result.is_valid)

    def test_missing_travel_configuration_is_reported(self) -> None:
        problem = self.build_problem(travel_times=())
        options = list(self.valid_options)
        options[1] = replace(options[1], start_period=4, end_period=6)

        result = validate_timetable(problem, tuple(options))

        self.assertIn(
            HardViolationCode.MISSING_TRAVEL_TIME,
            self.violation_codes(result),
        )

    def test_insufficient_travel_time_is_reported(self) -> None:
        options = list(self.valid_options)
        options[1] = replace(options[1], start_period=4, end_period=6)

        result = validate_timetable(self.problem, tuple(options))

        self.assertIn(
            HardViolationCode.INSUFFICIENT_TRAVEL_TIME,
            self.violation_codes(result),
        )

    def test_preferred_and_discouraged_windows_are_not_hard_violations(self) -> None:
        preferred_lecturer = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=2.0,
        )
        discouraged_room = AvailabilityWindow(
            resource_index=self.room_cs1.location_index,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
        )
        problem = self.build_problem(
            lecturer_availabilities=(preferred_lecturer,),
            room_availabilities=(discouraged_room,),
        )

        result = validate_timetable(problem, self.valid_options)

        self.assertTrue(result.is_valid)


if __name__ == "__main__":
    unittest.main()
