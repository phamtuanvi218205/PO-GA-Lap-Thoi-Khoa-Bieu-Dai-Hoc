"""Kiểm thử lớp repair mỏng đứng giữa decoder và optimizer."""

import unittest
from dataclasses import replace

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.decoder import DecodeStatus, decode_vector
from gapo_timetabling.models import SessionOption
from gapo_timetabling.repair import (
    RepairStatus,
    gene_for_option_index,
    repair_vector,
)
from tests.test_constraints import ConstraintFixture


class TestRepair(ConstraintFixture):
    """Xác nhận repair chỉ đổi gene và luôn giao việc xếp cho decoder."""

    def singleton_domains(self) -> tuple[tuple[SessionOption, ...], ...]:
        """Tạo miền chỉ có một option để kiểm tra trường hợp không thể đổi."""

        return tuple((option,) for option in self.valid_options)

    def make_backtracking_case(self):
        """Tạo trường hợp một điểm bắt đầu tốt giúp decoder dùng ít node hơn.

        Ba session đầu dùng cùng giảng viên và cùng phòng. Nếu session 0 ưu
        tiên tiết 4-6, decoder đi vào nhánh cụt và không kịp quay lui trong bốn
        node. Nếu đổi gene của session 0 để ưu tiên tiết 1-3, decoder tìm được
        lịch hợp lệ đúng trong cùng ngân sách bốn node.
        """

        same_lecturer_part = replace(self.parts[2], lecturer_index=0)
        problem = replace(
            self.problem,
            teaching_parts=(
                self.parts[0],
                self.parts[1],
                same_lecturer_part,
                self.parts[3],
            ),
        )

        option_0_early = SessionOption(0, 0, self.tuesday.calendar_date, 1, 3)
        option_0_middle = SessionOption(0, 0, self.tuesday.calendar_date, 4, 6)
        option_1_middle = SessionOption(1, 0, self.tuesday.calendar_date, 4, 6)
        option_1_late = SessionOption(1, 0, self.tuesday.calendar_date, 7, 9)
        option_2_middle = SessionOption(2, 0, self.tuesday.calendar_date, 4, 6)
        option_2_late = SessionOption(2, 0, self.tuesday.calendar_date, 7, 9)
        domains = (
            (option_0_early, option_0_middle),
            (option_1_middle, option_1_late),
            (option_2_middle, option_2_late),
            (self.valid_options[3],),
        )
        vector = (0.75, 0.25, 0.25, 0.0)
        return problem, domains, vector

    def test_valid_decode_does_not_need_repair(self) -> None:
        """Không sửa một vector vốn đã tạo được lịch hợp lệ."""

        vector = (0.0, 0.0, 0.0, 0.0)
        decoded = decode_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            max_decode_nodes=20,
        )

        result = repair_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            decoded,
            max_repair_attempts=3,
            max_decode_nodes_per_attempt=20,
        )

        self.assertEqual(result.status, RepairStatus.NOT_NEEDED)
        self.assertTrue(result.is_success)
        self.assertFalse(result.was_repaired)
        self.assertEqual(result.attempts, 0)
        self.assertIs(result.decode_result, decoded)

    def test_no_option_is_not_repairable(self) -> None:
        """Miền rỗng phải quay về sửa dữ liệu, không để repair tạo option giả."""

        domains = list(self.singleton_domains())
        domains[2] = ()
        domains = tuple(domains)
        vector = (0.0, 0.0, 0.0, 0.0)
        decoded = decode_vector(
            self.problem,
            domains,
            vector,
            max_decode_nodes=20,
        )

        result = repair_vector(
            self.problem,
            domains,
            vector,
            decoded,
            max_repair_attempts=3,
            max_decode_nodes_per_attempt=20,
        )

        self.assertEqual(decoded.status, DecodeStatus.NO_OPTION)
        self.assertEqual(result.status, RepairStatus.NOT_REPAIRABLE)
        self.assertEqual(result.attempts, 0)
        self.assertFalse(result.is_success)

    def test_changes_one_gene_then_decoder_finds_valid_schedule(self) -> None:
        """Repair đổi điểm ưu tiên; decoder vẫn là nơi tạo và kiểm tra lịch."""

        problem, domains, vector = self.make_backtracking_case()
        decoded = decode_vector(problem, domains, vector, max_decode_nodes=4)

        result = repair_vector(
            problem,
            domains,
            vector,
            decoded,
            max_repair_attempts=2,
            max_decode_nodes_per_attempt=4,
        )

        self.assertEqual(decoded.status, DecodeStatus.DECODE_FAILED)
        self.assertEqual(result.status, RepairStatus.REPAIRED)
        self.assertTrue(result.was_repaired)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.changed_session_index, 0)
        self.assertEqual(result.requested_option_index, 0)
        self.assertEqual(result.decode_result.selected_option_indices, (0, 0, 1, 0))
        self.assertEqual(result.decode_result.repaired_vector[0], 0.25)
        self.assertTrue(
            validate_timetable(
                problem,
                result.decode_result.selected_options,
            ).is_valid
        )

    def test_repair_does_not_mutate_input_vector_or_domains(self) -> None:
        """Dữ liệu snapshot và cá thể gốc phải giữ nguyên sau mọi lần thử."""

        problem, domains, vector = self.make_backtracking_case()
        original_vector = tuple(vector)
        original_domains = tuple(tuple(domain) for domain in domains)
        decoded = decode_vector(problem, domains, vector, max_decode_nodes=4)

        repair_vector(
            problem,
            domains,
            vector,
            decoded,
            max_repair_attempts=2,
            max_decode_nodes_per_attempt=4,
        )

        self.assertEqual(vector, original_vector)
        self.assertEqual(domains, original_domains)

    def test_attempt_limit_is_honored(self) -> None:
        """Repair dừng đúng giới hạn dù vẫn còn gene khác có thể thử."""

        problem, domains, vector = self.make_backtracking_case()
        decoded = decode_vector(problem, domains, vector, max_decode_nodes=4)

        result = repair_vector(
            problem,
            domains,
            vector,
            decoded,
            max_repair_attempts=1,
            max_decode_nodes_per_attempt=4,
        )

        self.assertEqual(result.status, RepairStatus.FAILED)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.changed_session_index, 1)
        self.assertFalse(result.is_success)

    def test_singleton_domains_have_no_legal_repair_move(self) -> None:
        """Không có option thay thế thì repair thất bại mà không gọi decoder."""

        vector = (0.0, 0.0, 0.0, 0.0)
        decoded = decode_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            max_decode_nodes=1,
        )

        result = repair_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            decoded,
            max_repair_attempts=3,
            max_decode_nodes_per_attempt=20,
        )

        self.assertEqual(decoded.status, DecodeStatus.DECODE_FAILED)
        self.assertEqual(result.status, RepairStatus.FAILED)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(result.total_nodes_explored, 0)

    def test_repeat_repair_is_deterministic(self) -> None:
        """Cùng input và ngân sách phải cho đúng cùng một kết quả repair."""

        problem, domains, vector = self.make_backtracking_case()
        decoded = decode_vector(problem, domains, vector, max_decode_nodes=4)

        first = repair_vector(problem, domains, vector, decoded, 2, 4)
        second = repair_vector(problem, domains, vector, decoded, 2, 4)

        self.assertEqual(first, second)

    def test_gene_for_option_uses_center_of_interval(self) -> None:
        """Gene đồng bộ phải nằm giữa ô option, không nằm trên ranh giới."""

        self.assertEqual(gene_for_option_index(0, 4), 0.125)
        self.assertEqual(gene_for_option_index(2, 4), 0.625)
        self.assertEqual(gene_for_option_index(3, 4), 0.875)

    def test_invalid_gene_mapping_is_rejected(self) -> None:
        """Không chấp nhận chỉ số option nằm ngoài miền."""

        with self.assertRaisesRegex(ValueError, "option_index"):
            gene_for_option_index(2, 2)

        with self.assertRaisesRegex(ValueError, "option_count"):
            gene_for_option_index(0, 0)

    def test_invalid_repair_budget_is_rejected(self) -> None:
        """Hai giới hạn phải dương để hành vi repair luôn rõ ràng."""

        vector = (0.0, 0.0, 0.0, 0.0)
        decoded = decode_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            max_decode_nodes=20,
        )

        with self.assertRaisesRegex(ValueError, "max_repair_attempts"):
            repair_vector(
                self.problem,
                self.singleton_domains(),
                vector,
                decoded,
                max_repair_attempts=0,
                max_decode_nodes_per_attempt=20,
            )

        with self.assertRaisesRegex(ValueError, "max_decode_nodes_per_attempt"):
            repair_vector(
                self.problem,
                self.singleton_domains(),
                vector,
                decoded,
                max_repair_attempts=1,
                max_decode_nodes_per_attempt=0,
            )


if __name__ == "__main__":
    unittest.main()
