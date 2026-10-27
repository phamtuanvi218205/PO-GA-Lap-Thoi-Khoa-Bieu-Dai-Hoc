"""Kiểm thử quyết định tối ưu đồng thời giảng viên và thời khóa biểu."""

import unittest
from dataclasses import replace

from gapo_timetabling.core.constraints import HardViolationCode, validate_timetable
from gapo_timetabling.core.decoder import DecodeStatus, decode_vector
from gapo_timetabling.core.encoder import (
    build_option_domains,
    build_recurring_patterns_for_group,
)
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.ga import GAConfig, run_ga
from gapo_timetabling.core.greedy_baseline import run_greedy_first_feasible
from gapo_timetabling.core.hybrid import HybridConfig, run_hybrid
from gapo_timetabling.core.models import (
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    LecturerCourseCapability,
    PartType,
    PlanningScenario,
    PlanningScenarioItem,
    ProblemInstance,
    TeachingDurationRule,
    TeachingPart,
    TeachingPlan,
)
from gapo_timetabling.core.repair import _candidate_vectors
from gapo_timetabling.core.po import PoConfig, run_po
from gapo_timetabling.core.population import (
    CandidateEvaluationConfig,
    initialize_population,
)
from gapo_timetabling.core.snapshot import build_gene_option_mapping
from tests.test_constraints import ConstraintFixture


class TestDynamicLecturerAssignment(unittest.TestCase):
    """Một gene cấp lớp phải điều khiển đồng thời lý thuyết và thực hành."""

    def build_problem(
        self,
        *,
        second_lecturer_max: int | None = None,
        first_lecturer_unavailable: bool = True,
    ) -> ProblemInstance:
        fixture = ConstraintFixture()
        fixture.setUp()
        lecturers = (
            replace(fixture.lecturers[0], max_teaching_periods=12),
            replace(fixture.lecturers[1], max_teaching_periods=second_lecturer_max),
        )
        parts = (
            replace(
                fixture.parts[0],
                teaching_part_index=0,
                teaching_part_id=20,
                part_code="KTDL01_LT",
                section_code="KTDL01",
                part_type=PartType.LECTURE,
                lecturer_index=None,
            ),
            replace(
                fixture.parts[0],
                teaching_part_index=1,
                teaching_part_id=21,
                part_code="KTDL01_TH",
                section_code="KTDL01",
                part_type=PartType.PRACTICE,
                lecturer_index=None,
            ),
        )
        plans = (
            replace(fixture.plans[0], teaching_plan_id=100, teaching_part_index=0),
            replace(fixture.plans[1], teaching_plan_id=101, teaching_part_index=1),
        )
        sessions = (
            replace(fixture.sessions[0], session_index=0, teaching_plan_id=100),
            replace(fixture.sessions[1], session_index=1, teaching_plan_id=101),
        )
        scenario = PlanningScenario(
            scenario_id=1,
            scenario_code="SCN_DYNAMIC",
            term_code=fixture.term.term_code,
            scope_type=fixture.scenario.scope_type,
            status=fixture.scenario.status,
            items=(PlanningScenarioItem(0, 100), PlanningScenarioItem(1, 101)),
        )
        capabilities = (
            LecturerCourseCapability(0, "KTDL", True, True, 1.0),
            LecturerCourseCapability(1, "KTDL", True, True, 0.5),
        )
        # Người thứ nhất đủ chuyên môn nhưng bận toàn bộ ngày duy nhất. Encoder
        # vẫn giữ option của người thứ hai để gene phân công có thể đổi nghiệm.
        unavailable_tuesday = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.WEEKDAY,
            iso_weekday=fixture.tuesday.iso_weekday,
            calendar_date=None,
            start_period=1,
            end_period=16,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        unavailable_wednesday = replace(
            unavailable_tuesday,
            iso_weekday=fixture.wednesday_holiday.iso_weekday,
        )
        return ProblemInstance(
            term=fixture.term,
            scenario=scenario,
            weeks=(fixture.week,),
            teaching_dates=(fixture.tuesday, fixture.wednesday_holiday),
            time_periods=fixture.time_periods,
            allowed_period_blocks=fixture.allowed_blocks,
            teaching_duration_rules=(
                TeachingDurationRule(PartType.LECTURE, 3, True),
                TeachingDurationRule(PartType.PRACTICE, 3, True),
            ),
            locations=(fixture.room_cs1, fixture.room_cs2),
            lecturers=lecturers,
            courses=fixture.courses,
            course_sections=(fixture.sections[0],),
            teaching_parts=parts,
            teaching_plans=plans,
            class_sessions=sessions,
            lecturer_availabilities=(
                (unavailable_tuesday, unavailable_wednesday)
                if first_lecturer_unavailable
                else ()
            ),
            room_availabilities=(),
            campus_travel_times=fixture.problem.campus_travel_times,
            constraint_settings=(),
            lecturer_course_capabilities=capabilities,
        )

    def test_greedy_baseline_uses_lecturer_with_recurring_patterns(self) -> None:
        problem = self.build_problem(first_lecturer_unavailable=True)
        domains = build_option_domains(problem)
        evaluation_config = CandidateEvaluationConfig(
            max_decode_nodes=1_000,
            enable_repair=True,
            max_repair_attempts=3,
        )

        first = run_greedy_first_feasible(
            problem,
            domains,
            evaluation_config,
        )
        second = run_greedy_first_feasible(
            problem,
            domains,
            evaluation_config,
        )

        self.assertTrue(first.is_success)
        self.assertIsNotNone(first.individual)
        self.assertEqual(first.metrics.fitness_evaluations, 1)
        self.assertEqual(first.vector, second.vector)
        self.assertEqual(
            first.individual.selected_option_indices,
            second.individual.selected_option_indices,
        )
        self.assertEqual(
            {option.lecturer_index for option in first.individual.selected_options},
            {1},
        )

    def test_vector_contains_assignment_gene_before_session_genes(self) -> None:
        problem = self.build_problem()
        self.assertEqual(problem.assignment_dimension, 1)
        self.assertEqual(problem.session_dimension, 2)
        self.assertEqual(problem.dimension, 3)
        self.assertEqual(problem.assignment_section_codes, ("KTDL01",))

    def test_assignment_gene_selects_one_lecturer_for_both_parts(self) -> None:
        problem = self.build_problem()
        domains = build_option_domains(problem)

        failed = decode_vector(problem, domains, (0.1, 0.1, 0.1), 100)
        self.assertEqual(failed.status, DecodeStatus.DECODE_FAILED)

        result = decode_vector(problem, domains, (0.9, 0.1, 0.1), 100)
        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_lecturer_indices, (1,))
        self.assertEqual(
            {option.lecturer_index for option in result.selected_options},
            {1},
        )
        self.assertTrue(validate_timetable(problem, result.selected_options).is_valid)

    def test_fitness_exposes_workload_and_course_suitability(self) -> None:
        problem = self.build_problem()
        domains = build_option_domains(problem)
        result = decode_vector(problem, domains, (0.9, 0.1, 0.1), 100)
        fitness = calculate_fitness(problem, result.selected_options, domains)

        self.assertAlmostEqual(fitness.breakdown.workload_balance_component, 0.5)
        self.assertAlmostEqual(fitness.breakdown.course_suitability_component, 0.5)
        self.assertAlmostEqual(fitness.lecturer_preference_score, 0.25)

    def test_hard_maximum_load_is_validated_after_assignment(self) -> None:
        problem = self.build_problem(second_lecturer_max=5)
        domains = build_option_domains(problem)
        result = decode_vector(problem, domains, (0.9, 0.1, 0.1), 100)

        self.assertEqual(result.status, DecodeStatus.DECODE_FAILED)
        # Tải phụ thuộc hoàn toàn vào gene phân công và tổng tiết của part.
        # Decoder phải loại cá thể chắc chắn quá tải trước khi mở bất kỳ node
        # xếp lịch nào; điều này giữ nguyên feasibility nhưng tránh backtracking
        # vô ích trên fixture lớn.
        self.assertEqual(result.nodes_explored, 0)
        self.assertEqual(result.backtracks, 0)
        self.assertIn("vượt giới hạn", result.reason)
        candidate_options = tuple(domain[0] for domain in domains)
        codes = {
            violation.code
            for violation in validate_timetable(problem, candidate_options).violations
        }
        # domain[0] belongs to lecturer 1 because lecturer 0 is unavailable.
        self.assertIn(HardViolationCode.LECTURER_LOAD_EXCEEDED, codes)

    def test_schedule_repair_uses_domain_of_selected_lecturer(self) -> None:
        """Khoảng gene lịch không được tính lẫn option của giảng viên khác."""

        problem = self.build_problem(first_lecturer_unavailable=False)
        domains = build_option_domains(problem)
        vector = (0.9, 0.1, 0.1)

        candidates = tuple(
            _candidate_vectors(problem, domains, vector, failed_session_index=0)
        )
        first_schedule_candidate = next(
            candidate
            for changed_session, _, candidate in candidates
            if changed_session == 0
        )

        selected_lecturer = 1
        conditional_count = len(
            build_recurring_patterns_for_group(
                problem,
                domains,
                group_index=0,
                lecturer_index=selected_lecturer,
            )
        )
        # Gene phải đi vào giữa khoảng của pattern cục bộ kế tiếp trong miền
        # của giảng viên đã chọn, không dùng miền của giảng viên khác.
        current_index = min(
            int(vector[1] * conditional_count),
            conditional_count - 1,
        )
        next_index = (current_index + 1) % conditional_count
        self.assertAlmostEqual(
            first_schedule_candidate[1],
            (next_index + 0.5) / conditional_count,
        )

    def test_mapping_explains_conditional_option_indices(self) -> None:
        problem = self.build_problem(first_lecturer_unavailable=False)
        domains = build_option_domains(problem)
        mapping = build_gene_option_mapping(problem, domains, "checksum")

        first_gene_options = mapping["genes"][0]["options"]
        indices_by_lecturer: dict[int, list[int]] = {}
        for option in first_gene_options:
            indices_by_lecturer.setdefault(option["lecturer_index"], []).append(
                option["conditional_option_index"]
            )

        self.assertEqual(
            indices_by_lecturer[0],
            list(range(len(indices_by_lecturer[0]))),
        )
        self.assertEqual(
            indices_by_lecturer[1],
            list(range(len(indices_by_lecturer[1]))),
        )

    def test_all_optimizers_process_assignment_and_schedule_genes(self) -> None:
        """GA, PO và GA–PO phải chạy trực tiếp trên cùng vector v2."""

        problem = self.build_problem()
        domains = build_option_domains(problem)
        evaluation_config = CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )
        initialization = initialize_population(
            problem,
            domains,
            population_size=4,
            max_initialization_attempts=100,
            seed=42,
            evaluation_config=evaluation_config,
        )
        self.assertTrue(initialization.is_success)

        budget = initialization.fitness_evaluations + 4
        results = (
            run_ga(
                problem,
                domains,
                initialization,
                GAConfig(
                    max_fitness_evaluations=budget,
                    max_offspring_attempts=3,
                    seed=7,
                    evaluation_config=evaluation_config,
                ),
            ),
            run_po(
                problem,
                domains,
                initialization,
                PoConfig(
                    max_fitness_evaluations=budget,
                    max_offspring_attempts=3,
                    seed=7,
                    evaluation_config=evaluation_config,
                ),
            ),
            run_hybrid(
                problem,
                domains,
                initialization,
                HybridConfig(
                    max_fitness_evaluations=budget,
                    max_offspring_attempts=3,
                    seed=7,
                    evaluation_config=evaluation_config,
                ),
            ),
        )

        for result in results:
            self.assertEqual(len(result.best_individual.vector), problem.dimension)
            self.assertEqual(
                {option.lecturer_index for option in result.best_individual.selected_options},
                {1},
            )


if __name__ == "__main__":
    unittest.main()
