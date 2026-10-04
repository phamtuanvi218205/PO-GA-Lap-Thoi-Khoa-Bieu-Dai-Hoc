"""Kiểm thử các công thức Gate F trên một lịch nhỏ có thể tính bằng tay."""

import unittest
from dataclasses import replace
from datetime import date, time, timedelta

from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.fitness import calculate_fitness, calculate_time_stability
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


class FitnessFixture(unittest.TestCase):
    """Tạo bốn buổi lặp qua bốn tuần để kiểm tra fitness dễ hiểu."""

    def setUp(self) -> None:
        self.term = AcademicTerm(
            term_code="2026_HK1",
            term_name="Học kỳ 1",
            start_date=date(2026, 8, 17),
            end_date=date(2026, 9, 13),
            status=AcademicTermStatus.PLANNING,
        )
        self.weeks = tuple(
            TermWeek(
                week_number=week_number,
                start_date=date(2026, 8, 17) + timedelta(weeks=week_number - 1),
                end_date=date(2026, 8, 23) + timedelta(weeks=week_number - 1),
            )
            for week_number in range(1, 5)
        )

        # Mỗi tuần có thứ Hai và thứ Ba. Các test đổi thứ chỉ cần thay option,
        # không cần sửa cấu trúc học kỳ hoặc sinh ngày giả bên ngoài snapshot.
        teaching_dates: list[TeachingDate] = []
        for week in self.weeks:
            monday = week.start_date
            tuesday = monday + timedelta(days=1)
            teaching_dates.extend(
                (
                    TeachingDate(
                        monday,
                        week.week_number,
                        monday.isoweekday(),
                        DateStatus.NORMAL,
                    ),
                    TeachingDate(
                        tuesday,
                        week.week_number,
                        tuesday.isoweekday(),
                        DateStatus.NORMAL,
                    ),
                )
            )
        self.teaching_dates = tuple(teaching_dates)

        self.time_periods = tuple(
            TimePeriod(
                period_number=period_number,
                start_time=time(6 + period_number, 0),
                end_time=time(6 + period_number, 50),
                session_type=SessionType.MORNING,
            )
            for period_number in range(1, 10)
        )
        self.allowed_blocks = (
            AllowedPeriodBlock(1, 3),
            AllowedPeriodBlock(4, 3),
            AllowedPeriodBlock(7, 3),
            AllowedPeriodBlock(1, 6),
        )

        # Lớp dự kiến 50 người. Phòng nhỏ 40 chỗ tạo shortage_ratio=0,2;
        # phòng lớn 60 chỗ không bị phạt sức chứa.
        self.small_room = Room(
            location_index=0,
            location_id=10,
            location_code="A101",
            location_name="Phòng A101",
            active=True,
            campus_code="CS1",
            room_type=RoomType.LECTURE_ROOM,
            capacity=40,
            equipment_quantities=(('PROJECTOR', 1),),
        )
        self.large_room = Room(
            location_index=1,
            location_id=11,
            location_code="A102",
            location_name="Phòng A102",
            active=True,
            campus_code="CS1",
            room_type=RoomType.LECTURE_ROOM,
            capacity=60,
            equipment_quantities=(('PROJECTOR', 1),),
        )

        self.lecturer = Lecturer(0, "GV01", "Giảng viên 01", "CS1")
        self.course = Course("JAVA", "Lập trình Java")
        self.section = CourseSection("JAVA01", "JAVA", "Java 01", 50)
        self.part = TeachingPart(
            teaching_part_index=0,
            teaching_part_id=20,
            part_code="JAVA01_LT",
            section_code="JAVA01",
            part_type=PartType.LECTURE,
            lecturer_index=0,
            total_periods=12,
            required_location_type=LocationType.PHYSICAL_ROOM,
            required_room_type=RoomType.LECTURE_ROOM,
            required_equipment=(('PROJECTOR', 1),),
        )
        self.plan = TeachingPlan(
            teaching_plan_id=100,
            plan_code="JAVA01_PLAN",
            teaching_part_index=0,
            status=TeachingPlanStatus.APPROVED,
            allows_intensive=False,
        )
        self.sessions = tuple(
            ClassSession(
                session_index=index,
                class_session_id=1000 + index,
                teaching_plan_id=100,
                session_number=index + 1,
                stability_group_no=1,
                week_number=index + 1,
                duration_periods=3,
                required_location_type=LocationType.PHYSICAL_ROOM,
            )
            for index in range(4)
        )
        self.scenario = PlanningScenario(
            scenario_id=1,
            scenario_code="SCN_FITNESS",
            term_code="2026_HK1",
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.LOCKED,
            items=(PlanningScenarioItem(0, 100),),
        )

        self.problem = self.build_problem()
        self.domains = tuple(
            self.domain_for_session(session.session_index)
            for session in self.sessions
        )
        self.stable_options = tuple(domain[0] for domain in self.domains)

    def build_problem(
        self,
        *,
        part: TeachingPart | None = None,
        sessions: tuple[ClassSession, ...] | None = None,
        lecturer_availabilities: tuple[AvailabilityWindow, ...] = (),
        room_availabilities: tuple[AvailabilityWindow, ...] = (),
    ) -> ProblemInstance:
        """Tạo snapshot mới, chỉ thay đúng dữ liệu mà từng test quan tâm."""

        return ProblemInstance(
            term=self.term,
            scenario=self.scenario,
            weeks=self.weeks,
            teaching_dates=self.teaching_dates,
            time_periods=self.time_periods,
            allowed_period_blocks=self.allowed_blocks,
            teaching_duration_rules=(
                TeachingDurationRule(PartType.LECTURE, 3, True),
                TeachingDurationRule(PartType.LECTURE, 6, True),
            ),
            locations=(self.small_room, self.large_room),
            lecturers=(self.lecturer,),
            courses=(self.course,),
            course_sections=(self.section,),
            teaching_parts=(part or self.part,),
            teaching_plans=(self.plan,),
            class_sessions=sessions or self.sessions,
            lecturer_availabilities=lecturer_availabilities,
            room_availabilities=room_availabilities,
            campus_travel_times=(),
            constraint_settings=(),
        )

    def monday_of_week(self, week_number: int) -> date:
        return self.weeks[week_number - 1].start_date

    def tuesday_of_week(self, week_number: int) -> date:
        return self.monday_of_week(week_number) + timedelta(days=1)

    def option(
        self,
        session_index: int,
        *,
        weekday: int = 1,
        start_period: int = 1,
        duration: int = 3,
        room_index: int = 0,
    ) -> SessionOption:
        """Tạo option hợp lệ cho đúng tuần của session được chỉ định."""

        week_number = self.sessions[session_index].week_number
        teaching_date = (
            self.monday_of_week(week_number)
            if weekday == 1
            else self.tuesday_of_week(week_number)
        )
        return SessionOption(
            session_index=session_index,
            location_index=room_index,
            teaching_date=teaching_date,
            start_period=start_period,
            end_period=start_period + duration - 1,
        )

    def domain_for_session(
        self,
        session_index: int,
    ) -> tuple[SessionOption, ...]:
        """Miền có đủ lựa chọn để test đổi ngày, tiết và phòng."""

        return (
            self.option(session_index, weekday=1, start_period=1, room_index=0),
            self.option(session_index, weekday=1, start_period=1, room_index=1),
            self.option(session_index, weekday=1, start_period=4, room_index=0),
            self.option(session_index, weekday=2, start_period=1, room_index=0),
            self.option(session_index, weekday=2, start_period=4, room_index=0),
        )


class TestTimeStability(FitnessFixture):
    """Kiểm tra tầng ưu tiên cao nhất về thứ và tiết bắt đầu."""

    def test_identical_weekly_pattern_has_zero_score(self) -> None:
        result = calculate_time_stability(
            self.problem,
            self.stable_options,
            self.domains,
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.comparable_session_count, 4)
        self.assertEqual(result.weekday_change_count, 0)
        self.assertEqual(result.start_period_change_count, 0)

    def test_one_weekday_change_is_counted(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=2, start_period=1)

        result = calculate_time_stability(
            self.problem,
            tuple(selected),
            self.domains,
        )

        self.assertEqual(result.weekday_change_count, 1)
        self.assertEqual(result.start_period_change_count, 0)
        self.assertAlmostEqual(result.score, 1 / 8)

    def test_one_start_period_change_is_counted(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=1, start_period=4)

        result = calculate_time_stability(
            self.problem,
            tuple(selected),
            self.domains,
        )

        self.assertEqual(result.weekday_change_count, 0)
        self.assertEqual(result.start_period_change_count, 1)
        self.assertAlmostEqual(result.score, 1 / 8)

    def test_changing_both_weekday_and_start_counts_two_components(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=2, start_period=4)

        result = calculate_time_stability(
            self.problem,
            tuple(selected),
            self.domains,
        )

        self.assertEqual(result.weekday_change_count, 1)
        self.assertEqual(result.start_period_change_count, 1)
        self.assertAlmostEqual(result.score, 2 / 8)

    def test_duration_change_with_same_start_is_not_a_time_change(self) -> None:
        longer_session = replace(self.sessions[3], duration_periods=6)
        sessions = self.sessions[:3] + (longer_session,)
        part = replace(self.part, total_periods=15)
        problem = self.build_problem(part=part, sessions=sessions)

        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=1, start_period=1, duration=6)
        domains = list(self.domains)
        domains[3] = (selected[3],)

        result = calculate_time_stability(
            problem,
            tuple(selected),
            tuple(domains),
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.start_period_change_count, 0)

    def test_session_without_standard_option_is_a_valid_exception(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=2, start_period=1)
        domains = list(self.domains)
        domains[3] = (selected[3],)

        result = calculate_time_stability(
            self.problem,
            tuple(selected),
            tuple(domains),
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.valid_exception_count, 1)
        self.assertEqual(result.comparable_session_count, 3)
        self.assertEqual(result.exceptions[0].session_index, 3)

    def test_change_is_not_exception_when_standard_option_still_exists(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, weekday=2, start_period=1)

        result = calculate_time_stability(
            self.problem,
            tuple(selected),
            self.domains,
        )

        self.assertEqual(result.valid_exception_count, 0)
        self.assertEqual(result.weekday_change_count, 1)

    def test_separate_stability_groups_are_not_compared_together(self) -> None:
        sessions = (
            replace(self.sessions[0], stability_group_no=1),
            replace(self.sessions[1], stability_group_no=1),
            replace(self.sessions[2], stability_group_no=2),
            replace(self.sessions[3], stability_group_no=2),
        )
        problem = self.build_problem(sessions=sessions)
        selected = (
            self.option(0, weekday=1, start_period=1),
            self.option(1, weekday=1, start_period=1),
            self.option(2, weekday=2, start_period=4),
            self.option(3, weekday=2, start_period=4),
        )

        result = calculate_time_stability(problem, selected, self.domains)

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.comparable_session_count, 4)

    def test_tied_mode_is_deterministic(self) -> None:
        selected = (
            self.option(0, weekday=1, start_period=4),
            self.option(1, weekday=2, start_period=1),
            self.option(2, weekday=1, start_period=4),
            self.option(3, weekday=2, start_period=1),
        )

        result = calculate_time_stability(
            self.problem,
            selected,
            self.domains,
        )

        # Hai mẫu cùng tần suất. Mẫu thứ Hai, tiết 4 thắng tie-break;
        # hai buổi thứ Ba, tiết 1 khác cả hai thành phần.
        self.assertEqual(result.weekday_change_count, 2)
        self.assertEqual(result.start_period_change_count, 2)
        self.assertEqual(result.score, 0.5)


class TestGeneralQuality(FitnessFixture):
    """Kiểm tra bốn thành phần của ``Q_general``."""

    def test_capacity_uses_duration_weighted_shortage_ratio(self) -> None:
        result = calculate_fitness(
            self.problem,
            self.stable_options,
            self.domains,
        )

        self.assertAlmostEqual(result.breakdown.capacity_component, 0.2)
        self.assertAlmostEqual(result.general_quality_score, 0.45 * 0.2)

    def test_fitness_accepts_domains_generated_by_real_encoder(self) -> None:
        """Fitness phải nối được với output thật của encoder, không chỉ fixture."""

        encoder_domains = build_option_domains(self.problem)

        result = calculate_fitness(
            self.problem,
            self.stable_options,
            encoder_domains,
        )

        self.assertEqual(result.time_stability_score, 0.0)
        self.assertAlmostEqual(result.breakdown.capacity_component, 0.2)

    def test_time_stability_dominates_better_general_quality(self) -> None:
        """Lịch ổn định phải thắng dù lịch kia dùng phòng đủ chỗ hơn."""

        stable_result = calculate_fitness(
            self.problem,
            self.stable_options,
            self.domains,
        )

        less_stable_options = tuple(
            self.option(
                index,
                weekday=2 if index == 3 else 1,
                start_period=1,
                room_index=1,
            )
            for index in range(4)
        )
        less_stable_domains = list(self.domains)
        less_stable_domains[3] = less_stable_domains[3] + (
            less_stable_options[3],
        )
        less_stable_result = calculate_fitness(
            self.problem,
            less_stable_options,
            tuple(less_stable_domains),
        )

        self.assertEqual(stable_result.time_stability_score, 0.0)
        self.assertGreater(less_stable_result.time_stability_score, 0.0)
        self.assertGreater(
            stable_result.general_quality_score,
            less_stable_result.general_quality_score,
        )
        self.assertLess(stable_result.fitness_key, less_stable_result.fitness_key)

    def test_room_change_is_a_light_general_quality_penalty(self) -> None:
        selected = list(self.stable_options)
        selected[3] = self.option(3, room_index=1)

        result = calculate_fitness(
            self.problem,
            tuple(selected),
            self.domains,
        )

        self.assertEqual(result.breakdown.room_change_count, 1)
        self.assertAlmostEqual(result.breakdown.room_stability_component, 0.25)
        # Ba buổi ở phòng nhỏ và một buổi ở phòng đủ chỗ: Q_capacity=0,15.
        expected_general = 0.45 * 0.15 + 0.10 * 0.25
        self.assertAlmostEqual(result.general_quality_score, expected_general)

    def test_lecturer_gap_counts_only_periods_between_same_day_sessions(self) -> None:
        sessions = (
            replace(
                self.sessions[0],
                session_index=0,
                session_number=1,
                stability_group_no=1,
                week_number=1,
            ),
            replace(
                self.sessions[1],
                session_index=1,
                session_number=2,
                stability_group_no=2,
                week_number=1,
            ),
        )
        part = replace(self.part, total_periods=6)
        problem = self.build_problem(part=part, sessions=sessions)
        selected = (
            SessionOption(0, 0, self.monday_of_week(1), 1, 3),
            SessionOption(1, 0, self.monday_of_week(1), 7, 9),
        )
        domains = ((selected[0],), (selected[1],))

        result = calculate_fitness(problem, selected, domains)

        # Khoảng trống là tiết 4--6: 3 tiết trống / 6 tiết giảng dạy.
        self.assertAlmostEqual(result.breakdown.gap_component, 0.5)

    def test_room_discouraged_counts_unique_overlapping_periods(self) -> None:
        discouraged = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=1,
            start_period=2,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
        )
        problem = self.build_problem(room_availabilities=(discouraged,))

        result = calculate_fitness(
            problem,
            self.stable_options,
            self.domains,
        )

        # Mỗi buổi 1--3 có hai tiết bị hạn chế, nên tỷ lệ là 2/3.
        self.assertAlmostEqual(
            result.breakdown.room_discouraged_component,
            2 / 3,
        )


class TestLecturerPreference(FitnessFixture):
    """Kiểm tra mong muốn giảng viên so với lựa chọn tốt nhất trong miền."""

    def test_missing_attainable_preferred_time_is_penalized(self) -> None:
        preferred = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=1,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=1.0,
        )
        problem = self.build_problem(lecturer_availabilities=(preferred,))
        selected = tuple(
            self.option(index, weekday=2, start_period=1)
            for index in range(4)
        )

        result = calculate_fitness(problem, selected, self.domains)

        self.assertEqual(result.lecturer_preference_score, 1.0)
        self.assertEqual(
            result.breakdown.lecturer_breakdown[0].evaluated_session_count,
            4,
        )

    def test_unattainable_preferred_time_is_not_penalized(self) -> None:
        preferred = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=1,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.PREFERRED,
            preference_weight=1.0,
        )
        problem = self.build_problem(lecturer_availabilities=(preferred,))
        selected = tuple(
            self.option(index, weekday=2, start_period=1)
            for index in range(4)
        )
        domains = tuple((option,) for option in selected)

        result = calculate_fitness(problem, selected, domains)

        self.assertEqual(result.lecturer_preference_score, 0.0)
        self.assertEqual(result.breakdown.lecturer_breakdown, ())

    def test_avoidable_discouraged_time_is_penalized(self) -> None:
        discouraged = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=1,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=1.0,
        )
        problem = self.build_problem(lecturer_availabilities=(discouraged,))

        result = calculate_fitness(
            problem,
            self.stable_options,
            self.domains,
        )

        self.assertEqual(result.lecturer_preference_score, 1.0)
        self.assertEqual(
            result.breakdown.lecturer_breakdown[0].discouraged_overlap_penalty,
            12.0,
        )

    def test_unavoidable_discouraged_time_is_not_penalized(self) -> None:
        discouraged = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=1,
            start_period=1,
            end_period=3,
            availability_type=AvailabilityType.DISCOURAGED,
            preference_weight=1.0,
        )
        problem = self.build_problem(lecturer_availabilities=(discouraged,))
        domains = tuple(
            (
                self.option(index, weekday=1, start_period=1, room_index=0),
                self.option(index, weekday=1, start_period=1, room_index=1),
            )
            for index in range(4)
        )

        result = calculate_fitness(
            problem,
            self.stable_options,
            domains,
        )

        self.assertEqual(result.lecturer_preference_score, 0.0)


class TestFitnessInputValidation(FitnessFixture):
    """Fitness phải từ chối lịch sai thay vì che lỗi bằng điểm phạt."""

    def test_invalid_hard_schedule_is_rejected(self) -> None:
        selected = list(self.stable_options)
        selected[0] = replace(
            selected[0],
            teaching_date=date(2026, 8, 19),
        )
        domains = list(self.domains)
        domains[0] = (selected[0],)

        with self.assertRaisesRegex(ValueError, "lịch đã hợp lệ"):
            calculate_fitness(self.problem, tuple(selected), tuple(domains))

    def test_selected_option_must_belong_to_its_domain(self) -> None:
        domains = list(self.domains)
        domains[0] = (domains[0][1],)

        with self.assertRaisesRegex(ValueError, "phải thuộc miền option"):
            calculate_fitness(
                self.problem,
                self.stable_options,
                tuple(domains),
            )

    def test_option_must_be_stored_in_matching_session_domain(self) -> None:
        domains = list(self.domains)
        domains[0] = (replace(domains[0][0], session_index=1),)

        with self.assertRaisesRegex(ValueError, "đúng session_index"):
            calculate_fitness(
                self.problem,
                self.stable_options,
                tuple(domains),
            )


if __name__ == "__main__":
    unittest.main()
