import unittest
from dataclasses import replace

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.decoder import DecodeStatus, decode_vector
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.models import (
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    SessionOption,
)
from tests.test_constraints import ConstraintFixture


class TestDecoder(ConstraintFixture):
    """Các trường hợp Gate E trên cùng fixture của validator độc lập."""

    def singleton_domains(self) -> tuple[tuple[SessionOption, ...], ...]:
        return tuple((option,) for option in self.valid_options)

    def test_decodes_a_complete_valid_schedule(self) -> None:
        vector = (0.0, 0.0, 0.0, 0.0)

        result = decode_vector(
            self.problem,
            self.singleton_domains(),
            vector,
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_options, self.valid_options)
        self.assertEqual(result.selected_option_indices, (0, 0, 0, 0))
        self.assertEqual(result.repaired_vector, vector)
        self.assertEqual(result.nodes_explored, 4)
        self.assertTrue(validate_timetable(self.problem, result.selected_options).is_valid)

    def test_real_encoder_domains_can_be_decoded(self) -> None:
        domains = build_option_domains(self.problem)
        vector = (0.1, 0.1, 0.1, 0.1)

        result = decode_vector(
            self.problem,
            domains,
            vector,
            max_decode_nodes=100,
        )

        self.assertTrue(result.is_success)
        self.assertEqual(len(result.selected_options), self.problem.dimension)
        self.assertTrue(validate_timetable(self.problem, result.selected_options).is_valid)

    def test_gene_one_selects_last_option(self) -> None:
        first_option = self.valid_options[0]
        alternate_option = replace(first_option, location_index=1)
        domains = (
            (first_option, alternate_option),
            (self.valid_options[1],),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (1.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[0], 1)
        self.assertEqual(result.repaired_vector[0], 1.0)

    def test_empty_domain_stops_before_search(self) -> None:
        domains = list(self.singleton_domains())
        domains[2] = ()

        result = decode_vector(
            self.problem,
            tuple(domains),
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.NO_OPTION)
        self.assertEqual(result.failed_session_index, 2)
        self.assertEqual(result.nodes_explored, 0)
        self.assertIn("1002", result.reason)

    def test_empty_domain_explains_missing_period_block(self) -> None:
        problem = replace(self.problem, allowed_period_blocks=())
        domains = list(self.singleton_domains())
        domains[0] = ()

        result = decode_vector(
            problem,
            tuple(domains),
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.NO_OPTION)
        self.assertIn("khung tiết", result.reason)

    def test_empty_domain_explains_hard_availability(self) -> None:
        unavailable = AvailabilityWindow(
            resource_index=0,
            scope_type=AvailabilityScopeType.DATE,
            calendar_date=self.tuesday.calendar_date,
            start_period=1,
            end_period=9,
            availability_type=AvailabilityType.UNAVAILABLE,
        )
        problem = replace(
            self.problem,
            lecturer_availabilities=(unavailable,),
        )
        domains = list(self.singleton_domains())
        domains[0] = ()

        result = decode_vector(
            problem,
            tuple(domains),
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.NO_OPTION)
        self.assertIn("UNAVAILABLE", result.reason)

    def test_conflicting_preference_switches_option_and_repairs_gene(self) -> None:
        # Session 0 ưu tiên tiết 7-9 nhưng cùng giảng viên với session 1.
        # Decoder phải chọn lại tiết 1-3 và đồng bộ gene vào giữa ô số 0.
        bad_preference = replace(self.valid_options[0], start_period=7, end_period=9)
        domains = (
            (self.valid_options[0], bad_preference),
            (self.valid_options[1],),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.75, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[0], 0)
        self.assertEqual(result.repaired_vector[0], 0.25)
        self.assertEqual(result.selected_options[0], self.valid_options[0])

    def test_backtracking_recovers_from_a_dead_end(self) -> None:
        # Ba session cùng giảng viên và phòng. Nếu session 0 chọn tiết 4-6,
        # hai session còn lại đều buộc phải chọn tiết 7-9 nên một buổi thất bại.
        # Quay lui sang tiết 1-3 sẽ xếp được cả ba.
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

        result = decode_vector(
            problem,
            domains,
            (0.75, 0.25, 0.25, 0.0),
            max_decode_nodes=30,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertGreater(result.backtracks, 0)
        self.assertEqual(result.selected_option_indices[0], 0)
        self.assertEqual(result.repaired_vector[0], 0.25)
        self.assertTrue(validate_timetable(problem, result.selected_options).is_valid)

    def test_budget_exhaustion_is_decode_failed_not_infeasible(self) -> None:
        result = decode_vector(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=1,
        )

        self.assertEqual(result.status, DecodeStatus.DECODE_FAILED)
        self.assertEqual(result.nodes_explored, 1)
        self.assertIn("max_decode_nodes", result.reason)
        self.assertEqual(result.selected_options, ())

    def test_nonempty_but_conflicting_domains_decode_failed(self) -> None:
        conflicting = replace(self.valid_options[1], start_period=1, end_period=3)
        domains = (
            (self.valid_options[0],),
            (conflicting,),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.DECODE_FAILED)
        self.assertIsNotNone(result.failed_session_index)
        self.assertEqual(result.selected_options, ())

    def test_invalid_option_in_domain_is_not_selected(self) -> None:
        holiday = replace(
            self.valid_options[0],
            teaching_date=self.wednesday_holiday.calendar_date,
        )
        domains = (
            (holiday, self.valid_options[0]),
            (self.valid_options[1],),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.25, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[0], 1)
        self.assertEqual(result.repaired_vector[0], 0.75)

    def test_nonempty_domain_with_only_invalid_option_decode_failed(self) -> None:
        holiday = replace(
            self.valid_options[0],
            teaching_date=self.wednesday_holiday.calendar_date,
        )
        domains = (
            (holiday,),
            (self.valid_options[1],),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.0, 0.0, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.DECODE_FAILED)
        self.assertEqual(result.failed_session_index, 0)
        self.assertEqual(result.nodes_explored, 0)

    def test_repeat_run_is_deterministic(self) -> None:
        domains = build_option_domains(self.problem)
        vector = (0.4, 0.6, 0.2, 0.8)

        first = decode_vector(self.problem, domains, vector, max_decode_nodes=100)
        second = decode_vector(self.problem, domains, vector, max_decode_nodes=100)

        self.assertEqual(first, second)

    def test_wrong_domain_session_index_is_rejected(self) -> None:
        domains = list(self.singleton_domains())
        domains[0] = (replace(self.valid_options[0], session_index=1),)

        with self.assertRaisesRegex(ValueError, "session_index"):
            decode_vector(
                self.problem,
                tuple(domains),
                (0.0, 0.0, 0.0, 0.0),
                max_decode_nodes=20,
            )

    def test_gene_outside_boundary_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[0,1\]"):
            decode_vector(
                self.problem,
                self.singleton_domains(),
                (-0.1, 0.0, 0.0, 0.0),
                max_decode_nodes=20,
            )

    def test_zero_node_budget_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_decode_nodes"):
            decode_vector(
                self.problem,
                self.singleton_domains(),
                (0.0, 0.0, 0.0, 0.0),
                max_decode_nodes=0,
            )


if __name__ == "__main__":
    unittest.main()
