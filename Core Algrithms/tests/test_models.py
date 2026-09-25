import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, time

from gapo_timetabling.models import (
    AcademicTerm,
    AcademicTermStatus,
    AllowedPeriodBlock,
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    ConstraintSetting,
    ConstraintType,
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
    SessionType,
    TeachingDate,
    TeachingDurationRule,
    TeachingPart,
    TeachingPlan,
    TeachingPlanStatus,
    TermWeek,
    TimePeriod,
)


class TestModels(unittest.TestCase):
    """Kiểm tra hợp đồng dữ liệu mới trước khi viết lại encoder."""

    def setUp(self) -> None:
        # Học kỳ mẫu có hai tuần. Ngày thực tế là dữ liệu chính của lịch.
        self.term = AcademicTerm(
            term_code="2026_HK1",
            term_name="Học kỳ 1 năm học 2026-2027",
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 30),
            status=AcademicTermStatus.PLANNING,
        )
        self.weeks = (
            TermWeek(1, date(2026, 8, 17), date(2026, 8, 23)),
            TermWeek(2, date(2026, 8, 24), date(2026, 8, 30)),
        )
        self.teaching_dates = (
            TeachingDate(date(2026, 8, 18), 1, 2, DateStatus.NORMAL),
            TeachingDate(date(2026, 8, 25), 2, 2, DateStatus.NORMAL),
        )
        self.time_periods = tuple(
            TimePeriod(
                period_number=number,
                start_time=time(6 + number, 0),
                end_time=time(6 + number, 50),
                session_type=SessionType.MORNING,
            )
            for number in range(1, 7)
        )
        self.duration_rules = (
            TeachingDurationRule(PartType.LECTURE, 3, True),
            TeachingDurationRule(PartType.LECTURE, 6, True),
            TeachingDurationRule(PartType.PRACTICE, 5, True),
            TeachingDurationRule(PartType.PRACTICE, 6, True),
        )

        # Phòng chỉ có 30 chỗ trong khi lớp dự kiến 60 người.
        # Model vẫn chấp nhận vì sức chứa là tiêu chí mềm, không phải hard constraint.
        self.small_room = Room(
            location_index=0,
            location_id=1,
            location_code="F201",
            location_name="Phòng F201",
            active=True,
            campus_code="CS1",
            room_type=RoomType.LECTURE_ROOM,
            capacity=30,
            equipment_quantities=(("PROJECTOR", 1),),
        )
        self.zoom = OnlineLocation(
            location_index=1,
            location_id=2,
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
            CourseSection("KTDL01", "KTDL", "Khai thác dữ liệu 01", 60),
            CourseSection("TTNT01", "TTNT", "Trí tuệ nhân tạo 01", None),
        )

        self.lecture_part = TeachingPart(
            teaching_part_index=0,
            teaching_part_id=10,
            part_code="KTDL01_LT",
            section_code="KTDL01",
            part_type=PartType.LECTURE,
            lecturer_index=0,
            total_periods=6,
            required_location_type=LocationType.PHYSICAL_ROOM,
            required_room_type=RoomType.LECTURE_ROOM,
            required_equipment=(("PROJECTOR", 1),),
        )
        self.online_part = TeachingPart(
            teaching_part_index=1,
            teaching_part_id=11,
            part_code="TTNT01_LT",
            section_code="TTNT01",
            part_type=PartType.LECTURE,
            lecturer_index=1,
            total_periods=3,
            required_location_type=LocationType.ONLINE,
            required_room_type=None,
        )

        self.lecture_plan = TeachingPlan(
            teaching_plan_id=100,
            plan_code="KTDL01_STANDARD",
            teaching_part_index=0,
            status=TeachingPlanStatus.APPROVED,
            allows_intensive=False,
        )
        self.online_plan = TeachingPlan(
            teaching_plan_id=101,
            plan_code="TTNT01_ONLINE",
            teaching_part_index=1,
            status=TeachingPlanStatus.APPROVED,
            allows_intensive=False,
        )

        # Ba session dưới đây chính là ba gene của một cá thể.
        self.sessions = (
            ClassSession(0, 1000, 100, 1, 1, 3, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1001, 100, 2, 2, 3, LocationType.PHYSICAL_ROOM),
            ClassSession(2, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )
        self.scenario = PlanningScenario(
            scenario_id=1,
            scenario_code="SCN_2026_HK1_FULL_01",
            term_code="2026_HK1",
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.LOCKED,
            items=(
                PlanningScenarioItem(0, 100),
                PlanningScenarioItem(1, 101),
            ),
        )

        self.lecturer_preference = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=6,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=1.0,
        )
        self.constraints = (
            ConstraintSetting(
                constraint_code="HARD_LECTURER_OVERLAP",
                constraint_type=ConstraintType.HARD,
                priority_tier=1,
                weight=None,
                enabled=True,
            ),
            ConstraintSetting(
                constraint_code="SOFT_CAPACITY",
                constraint_type=ConstraintType.SOFT,
                priority_tier=2,
                weight=None,
                enabled=True,
            ),
        )

        self.problem = self._build_problem(self.sessions)

    def _build_problem(
        self,
        sessions: tuple[ClassSession, ...],
        scenario: PlanningScenario | None = None,
        teaching_parts: tuple[TeachingPart, ...] | None = None,
        duration_rules: tuple[TeachingDurationRule, ...] | None = None,
        weeks: tuple[TermWeek, ...] | None = None,
        teaching_dates: tuple[TeachingDate, ...] | None = None,
    ) -> ProblemInstance:
        return ProblemInstance(
            term=self.term,
            scenario=scenario or self.scenario,
            weeks=self.weeks if weeks is None else weeks,
            teaching_dates=(
                self.teaching_dates
                if teaching_dates is None
                else teaching_dates
            ),
            time_periods=self.time_periods,
            allowed_period_blocks=(AllowedPeriodBlock(1, 3),),
            teaching_duration_rules=duration_rules or self.duration_rules,
            locations=(self.small_room, self.zoom),
            lecturers=self.lecturers,
            courses=self.courses,
            course_sections=self.sections,
            teaching_parts=teaching_parts or (self.lecture_part, self.online_part),
            teaching_plans=(self.lecture_plan, self.online_plan),
            class_sessions=sessions,
            lecturer_availabilities=(self.lecturer_preference,),
            room_availabilities=(),
            campus_travel_times=(),
            constraint_settings=self.constraints,
        )

    def test_dimension_equals_class_session_count(self) -> None:
        self.assertEqual(self.problem.dimension, 3)
        self.assertEqual(
            tuple(session.session_index for session in self.problem.class_sessions),
            (0, 1, 2),
        )

    def test_each_session_belongs_to_one_specific_week(self) -> None:
        self.assertEqual(self.sessions[0].week_number, 1)
        self.assertEqual(self.sessions[1].week_number, 2)

    def test_teaching_date_inside_declared_week_is_allowed(self) -> None:
        self.assertEqual(self.problem.teaching_dates, self.teaching_dates)

    def test_teaching_date_outside_declared_week_is_rejected(self) -> None:
        monday_of_week_two = TeachingDate(
            calendar_date=date(2026, 8, 24),
            week_number=1,
            iso_weekday=1,
            status=DateStatus.NORMAL,
        )

        with self.assertRaisesRegex(ValueError, "không nằm trong tuần"):
            self._build_problem(
                self.sessions,
                teaching_dates=(monday_of_week_two, self.teaching_dates[1]),
            )

    def test_teaching_date_outside_term_is_rejected(self) -> None:
        outside_term = TeachingDate(
            calendar_date=date(2026, 9, 1),
            week_number=2,
            iso_weekday=2,
            status=DateStatus.NORMAL,
        )

        with self.assertRaisesRegex(ValueError, "nằm ngoài học kỳ"):
            self._build_problem(
                self.sessions,
                teaching_dates=(self.teaching_dates[0], outside_term),
            )

    def test_teaching_date_referencing_unknown_week_is_rejected(self) -> None:
        date_with_unknown_week = TeachingDate(
            calendar_date=date(2026, 8, 19),
            week_number=3,
            iso_weekday=3,
            status=DateStatus.NORMAL,
        )

        with self.assertRaisesRegex(ValueError, "tham chiếu tuần không tồn tại"):
            self._build_problem(
                self.sessions,
                teaching_dates=(
                    self.teaching_dates[0],
                    self.teaching_dates[1],
                    date_with_unknown_week,
                ),
            )

    def test_term_week_outside_term_is_rejected(self) -> None:
        week_extending_past_term = TermWeek(
            week_number=2,
            start_date=date(2026, 8, 24),
            end_date=date(2026, 9, 1),
        )

        with self.assertRaisesRegex(ValueError, "Tuần 2.*ngoài"):
            self._build_problem(
                self.sessions,
                weeks=(self.weeks[0], week_extending_past_term),
            )

    def test_duplicate_week_numbers_are_rejected(self) -> None:
        duplicate_week_number = TermWeek(
            week_number=1,
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 30),
        )

        with self.assertRaisesRegex(ValueError, "không được trùng"):
            self._build_problem(
                self.sessions,
                weeks=(self.weeks[0], duplicate_week_number),
            )

    def test_duplicate_teaching_dates_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "không được trùng ngày"):
            self._build_problem(
                self.sessions,
                teaching_dates=(
                    self.teaching_dates[0],
                    self.teaching_dates[0],
                    self.teaching_dates[1],
                ),
            )

    def test_session_referencing_unknown_week_is_rejected(self) -> None:
        unknown_week_sessions = (
            self.sessions[0],
            replace(self.sessions[1], week_number=3),
            self.sessions[2],
        )

        with self.assertRaisesRegex(ValueError, "tuần không tồn tại"):
            self._build_problem(unknown_week_sessions)

    def test_lecture_session_with_three_periods_is_allowed(self) -> None:
        self.assertEqual(self.sessions[0].duration_periods, 3)
        self.assertEqual(self.problem.dimension, 3)

    def test_lecture_session_with_six_periods_is_allowed(self) -> None:
        six_period_sessions = (
            ClassSession(0, 1000, 100, 1, 1, 6, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        problem = self._build_problem(six_period_sessions)

        self.assertEqual(problem.class_sessions[0].duration_periods, 6)

    def test_lecture_session_with_five_periods_is_rejected(self) -> None:
        five_period_part = replace(self.lecture_part, total_periods=5)
        five_period_sessions = (
            ClassSession(0, 1000, 100, 1, 1, 5, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        with self.assertRaisesRegex(ValueError, "không được phép"):
            self._build_problem(
                five_period_sessions,
                teaching_parts=(five_period_part, self.online_part),
            )

    def test_practice_session_with_five_periods_is_allowed(self) -> None:
        practice_part = replace(
            self.lecture_part,
            part_type=PartType.PRACTICE,
            total_periods=5,
        )
        practice_sessions = (
            ClassSession(0, 1000, 100, 1, 1, 5, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        problem = self._build_problem(
            practice_sessions,
            teaching_parts=(practice_part, self.online_part),
        )

        self.assertEqual(problem.class_sessions[0].duration_periods, 5)

    def test_practice_session_with_six_periods_is_allowed(self) -> None:
        practice_part = replace(
            self.lecture_part,
            part_type=PartType.PRACTICE,
        )
        practice_sessions = (
            ClassSession(0, 1000, 100, 1, 1, 6, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        problem = self._build_problem(
            practice_sessions,
            teaching_parts=(practice_part, self.online_part),
        )

        self.assertEqual(problem.class_sessions[0].duration_periods, 6)

    def test_practice_session_with_three_periods_is_rejected(self) -> None:
        practice_part = replace(
            self.lecture_part,
            part_type=PartType.PRACTICE,
        )

        with self.assertRaisesRegex(ValueError, "không được phép"):
            self._build_problem(
                self.sessions,
                teaching_parts=(practice_part, self.online_part),
            )

    def test_missing_duration_rules_for_part_type_is_rejected(self) -> None:
        lecture_rules_only = (
            TeachingDurationRule(PartType.LECTURE, 3, True),
            TeachingDurationRule(PartType.LECTURE, 6, True),
        )
        practice_part = replace(
            self.lecture_part,
            part_type=PartType.PRACTICE,
            total_periods=5,
        )
        practice_sessions = (
            ClassSession(0, 1000, 100, 1, 1, 5, LocationType.PHYSICAL_ROOM),
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        with self.assertRaisesRegex(ValueError, "Chưa khai báo"):
            self._build_problem(
                practice_sessions,
                teaching_parts=(practice_part, self.online_part),
                duration_rules=lecture_rules_only,
            )

    def test_selected_plans_have_exactly_the_required_periods(self) -> None:
        lecture_total = sum(
            session.duration_periods
            for session in self.problem.class_sessions
            if session.teaching_plan_id == self.lecture_plan.teaching_plan_id
        )
        self.assertEqual(lecture_total, self.lecture_part.total_periods)

    def test_wrong_plan_total_is_rejected(self) -> None:
        incomplete_sessions = (
            self.sessions[0],
            ClassSession(1, 1002, 101, 1, 1, 3, LocationType.ONLINE),
        )

        with self.assertRaisesRegex(ValueError, "không bằng"):
            self._build_problem(incomplete_sessions)

    def test_scenario_cannot_select_two_plans_for_one_part(self) -> None:
        with self.assertRaisesRegex(ValueError, "một plan"):
            PlanningScenario(
                scenario_id=2,
                scenario_code="INVALID",
                term_code="2026_HK1",
                scope_type=ScenarioScopeType.FULL_TERM,
                status=PlanningScenarioStatus.LOCKED,
                items=(
                    PlanningScenarioItem(0, 100),
                    PlanningScenarioItem(0, 999),
                ),
            )

    def test_unlocked_scenario_cannot_start_an_optimization_run(self) -> None:
        draft_scenario = PlanningScenario(
            scenario_id=2,
            scenario_code="DRAFT_SCENARIO",
            term_code="2026_HK1",
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.DRAFT,
            items=self.scenario.items,
        )

        with self.assertRaisesRegex(ValueError, "LOCKED"):
            self._build_problem(self.sessions, draft_scenario)

    def test_room_shortage_does_not_make_problem_invalid(self) -> None:
        self.assertEqual(self.sections[0].expected_enrollment, 60)
        self.assertEqual(self.small_room.capacity, 30)
        self.assertEqual(len(self.problem.rooms), 1)

    def test_unknown_expected_enrollment_is_allowed(self) -> None:
        self.assertIsNone(self.sections[1].expected_enrollment)

    def test_online_location_is_not_a_physical_room(self) -> None:
        self.assertEqual(self.zoom.location_type, LocationType.ONLINE)
        self.assertEqual(len(self.problem.online_locations), 1)
        self.assertEqual(len(self.problem.rooms), 1)

    def test_student_data_no_longer_exists_in_problem_instance(self) -> None:
        self.assertFalse(hasattr(self.problem, "student_groups"))
        self.assertFalse(hasattr(self.sessions[0], "student_group_indices"))

    def test_model_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.small_room.capacity = 100

    def test_enum_values_match_sql_and_java(self) -> None:
        self.assertEqual(RoomType.LECTURE_ROOM.value, "LECTURE_ROOM")
        self.assertEqual(LocationType.PHYSICAL_ROOM.value, "PHYSICAL_ROOM")
        self.assertEqual(AvailabilityType.PREFERRED.value, "PREFERRED")

    def test_availability_scope_must_be_unambiguous(self) -> None:
        with self.assertRaisesRegex(ValueError, "DATE"):
            AvailabilityWindow(
                resource_index=0,
                scope_type=AvailabilityScopeType.DATE,
                calendar_date=None,
                iso_weekday=2,
                start_period=1,
                end_period=3,
                availability_type=AvailabilityType.UNAVAILABLE,
            )

    def test_room_discouraged_without_weight_matches_sql_schema(self) -> None:
        discouraged_room = AvailabilityWindow(
            resource_index=self.small_room.location_index,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=None,
        )

        problem = replace(
            self.problem,
            room_availabilities=(discouraged_room,),
        )

        self.assertEqual(problem.room_availabilities, (discouraged_room,))

    def test_lecturer_discouraged_without_weight_is_rejected(self) -> None:
        discouraged_lecturer = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=None,
        )

        with self.assertRaisesRegex(ValueError, "phải có trọng số"):
            replace(
                self.problem,
                lecturer_availabilities=(discouraged_lecturer,),
            )

    def test_room_preferred_is_rejected_because_sql_does_not_support_it(self) -> None:
        preferred_room = AvailabilityWindow(
            resource_index=self.small_room.location_index,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=1.0,
        )

        with self.assertRaisesRegex(ValueError, "không hỗ trợ PREFERRED"):
            replace(
                self.problem,
                room_availabilities=(preferred_room,),
            )

    def test_room_availability_with_weight_is_rejected(self) -> None:
        weighted_room_window = AvailabilityWindow(
            resource_index=self.small_room.location_index,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=1.0,
        )

        with self.assertRaisesRegex(ValueError, "không lưu preference_weight"):
            replace(
                self.problem,
                room_availabilities=(weighted_room_window,),
            )

    def test_availability_cannot_reference_unknown_resource(self) -> None:
        unknown_lecturer = AvailabilityWindow(
            resource_index=99,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )

        with self.assertRaisesRegex(ValueError, "giảng viên không tồn tại"):
            replace(
                self.problem,
                lecturer_availabilities=(unknown_lecturer,),
            )

    def test_room_availability_cannot_reference_online_location(self) -> None:
        online_location_window = AvailabilityWindow(
            resource_index=self.zoom.location_index,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=2,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.UNAVAILABLE,
        )

        with self.assertRaisesRegex(ValueError, "phòng không tồn tại"):
            replace(
                self.problem,
                room_availabilities=(online_location_window,),
            )


if __name__ == "__main__":
    unittest.main()
