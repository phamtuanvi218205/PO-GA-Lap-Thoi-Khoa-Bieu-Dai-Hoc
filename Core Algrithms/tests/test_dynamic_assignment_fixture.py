"""Kiểm thử fixture v2 dùng cho pilot phân công giảng viên động."""

import unittest
from collections import defaultdict
from pathlib import Path

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.decoder import DecodeStatus, decode_vector
from gapo_timetabling.snapshot import prepare_snapshot_for_optimization


SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "demo_data"
    / "dynamic_assignment_snapshot_v2.json"
)


class TestDynamicAssignmentFixture(unittest.TestCase):
    """Bảo vệ độ khó và một chứng cứ khả thi xác định của fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prepared = prepare_snapshot_for_optimization(SNAPSHOT_PATH)
        cls.problem = cls.prepared.problem
        cls.domains = cls.prepared.option_domains

    def test_fixture_has_competing_assignment_and_schedule_domains(self) -> None:
        problem = self.problem
        self.assertEqual(problem.assignment_dimension, 9)
        self.assertEqual(problem.session_dimension, 108)
        self.assertEqual(problem.schedule_dimension, 18)
        self.assertEqual(problem.dimension, 27)
        self.assertGreaterEqual(len(problem.lecturer_course_capabilities), 19)
        self.assertGreater(sum(map(len, self.domains)), 2_000)
        self.assertTrue(all(len(domain) >= 9 for domain in self.domains))

        # Mỗi lớp phải có ít nhất ba người đủ năng lực. Capability CSDL chỉ
        # có lý thuyết của GV005 không được tính vì lớp còn có thực hành.
        for section_code in problem.assignment_section_codes:
            self.assertGreaterEqual(
                len(problem.eligible_lecturer_indices(section_code)),
                3,
            )
        self.assertNotIn(4, problem.eligible_lecturer_indices("CSDL01"))

        total_required_periods = sum(
            part.total_periods for part in problem.teaching_parts
        )
        total_maximum_load = sum(
            lecturer.max_teaching_periods or total_required_periods
            for lecturer in problem.lecturers
        )
        # Chỉ dư đúng sức tải của một lớp: có cạnh tranh tải nhưng không vô nghiệm.
        self.assertEqual(total_required_periods, 432)
        self.assertEqual(total_maximum_load - total_required_periods, 48)

    def test_fixture_contains_a_known_feasible_assignment(self) -> None:
        problem = self.problem
        target_lecturers = (0, 1, 2, 3, 0, 1, 2, 3, 4)
        assignment_genes = []
        for section_code, lecturer_index in zip(
            problem.assignment_section_codes,
            target_lecturers,
        ):
            eligible = problem.eligible_lecturer_indices(section_code)
            local_index = eligible.index(lecturer_index)
            assignment_genes.append((local_index + 0.5) / len(eligible))

        vector = tuple(assignment_genes) + (0.5,) * problem.schedule_dimension
        result = decode_vector(problem, self.domains, vector, 20_000)
        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_lecturer_indices, target_lecturers)
        self.assertTrue(
            validate_timetable(problem, result.selected_options).is_valid
        )

        load_by_lecturer: dict[int, int] = defaultdict(int)
        for option in result.selected_options:
            load_by_lecturer[problem.option_lecturer_index(option)] += (
                option.end_period - option.start_period + 1
            )
        for lecturer in problem.lecturers:
            if lecturer.max_teaching_periods is not None:
                self.assertLessEqual(
                    load_by_lecturer[lecturer.lecturer_index],
                    lecturer.max_teaching_periods,
                )


if __name__ == "__main__":
    unittest.main()
