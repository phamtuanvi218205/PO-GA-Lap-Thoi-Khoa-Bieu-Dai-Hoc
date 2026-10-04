"""Kiểm thử tích hợp nhỏ cho decoder với nhiều buổi và loại xung đột."""

from dataclasses import replace
from datetime import timedelta
import random
import unittest

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.decoder import DecodeStatus, decode_vector
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.models import DateStatus, SessionOption, TeachingDate
from tests.decoder_scenarios import make_multisession_problem, make_stress_domains
from tests.test_constraints import ConstraintFixture


class TestDecoderMultisession(ConstraintFixture):
    def test_encoder_domains_decode_twelve_sessions_across_three_weeks(self) -> None:
        problem = make_multisession_problem(3)
        domains = build_option_domains(problem)
        rng = random.Random(20260919)
        vector = tuple(rng.random() for _ in range(problem.dimension))

        result = decode_vector(problem, domains, vector, max_decode_nodes=200)

        self.assertEqual(problem.dimension, 12)
        self.assertTrue(all(domains))
        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertTrue(validate_timetable(problem, result.selected_options).is_valid)
        self.assertLessEqual(result.nodes_explored, 200)

    def test_stress_domains_are_deterministic_and_repair_matches_selection(self) -> None:
        problem = make_multisession_problem(3)
        domains = make_stress_domains(problem)
        rng = random.Random(20260920)
        vector = tuple(rng.random() for _ in range(problem.dimension))

        first = decode_vector(problem, domains, vector, max_decode_nodes=100)
        second = decode_vector(problem, domains, vector, max_decode_nodes=100)

        self.assertEqual(first, second)
        self.assertEqual(first.status, DecodeStatus.SUCCESS)
        self.assertTrue(validate_timetable(problem, first.selected_options).is_valid)
        for session_index, selected_index in enumerate(first.selected_option_indices):
            domain_size = len(domains[session_index])
            mapped_index = min(
                int(first.repaired_vector[session_index] * domain_size),
                domain_size - 1,
            )
            self.assertEqual(mapped_index, selected_index)

    def test_small_node_budget_reports_decode_failed(self) -> None:
        problem = make_multisession_problem(3)
        domains = make_stress_domains(problem)
        vector = (0.75,) * problem.dimension

        result = decode_vector(problem, domains, vector, max_decode_nodes=5)

        self.assertEqual(result.status, DecodeStatus.DECODE_FAILED)
        self.assertEqual(result.nodes_explored, 5)
        self.assertIn("max_decode_nodes", result.reason)

    def test_forty_seeded_vectors_find_valid_stress_schedules(self) -> None:
        problem = make_multisession_problem(3)
        domains = make_stress_domains(problem)

        for seed in range(40):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                vector = tuple(rng.random() for _ in range(problem.dimension))
                result = decode_vector(problem, domains, vector, max_decode_nodes=40)
                repeated = decode_vector(problem, domains, vector, max_decode_nodes=40)

                self.assertEqual(result.status, DecodeStatus.SUCCESS)
                self.assertEqual(result, repeated)
                self.assertTrue(
                    validate_timetable(problem, result.selected_options).is_valid
                )
                self.assertLessEqual(result.nodes_explored, 40)

    def test_travel_time_forces_later_option(self) -> None:
        early_cs1 = SessionOption(0, 0, self.tuesday.calendar_date, 1, 3)
        middle_cs2 = SessionOption(1, 1, self.tuesday.calendar_date, 4, 6)
        late_cs2 = SessionOption(1, 1, self.tuesday.calendar_date, 7, 9)
        domains = (
            (early_cs1,),
            (middle_cs2, late_cs2),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.0, 0.25, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[1], 1)
        self.assertEqual(result.repaired_vector[1], 0.75)
        self.assertTrue(validate_timetable(self.problem, result.selected_options).is_valid)

    def test_room_collision_forces_other_period(self) -> None:
        early_same_room = SessionOption(2, 0, self.tuesday.calendar_date, 1, 3)
        middle_same_room = self.valid_options[2]
        domains = (
            (self.valid_options[0],),
            (self.valid_options[1],),
            (early_same_room, middle_same_room),
            (self.valid_options[3],),
        )

        result = decode_vector(
            self.problem,
            domains,
            (0.0, 0.0, 0.25, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[2], 1)
        self.assertTrue(validate_timetable(self.problem, result.selected_options).is_valid)

    def test_conflict_can_move_session_to_another_date(self) -> None:
        thursday_date = self.tuesday.calendar_date + timedelta(days=2)
        thursday = TeachingDate(thursday_date, 1, 4, DateStatus.NORMAL)
        problem = replace(
            self.problem,
            teaching_dates=self.problem.teaching_dates + (thursday,),
        )
        conflicting_tuesday = SessionOption(
            1, 1, self.tuesday.calendar_date, 1, 3
        )
        free_thursday = SessionOption(1, 1, thursday_date, 1, 3)
        domains = (
            (self.valid_options[0],),
            (conflicting_tuesday, free_thursday),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )

        result = decode_vector(
            problem,
            domains,
            (0.0, 0.25, 0.0, 0.0),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_options[1].teaching_date, thursday_date)
        self.assertEqual(result.repaired_vector[1], 0.75)
        self.assertTrue(validate_timetable(problem, result.selected_options).is_valid)

    def test_online_still_occupies_lecturer_time(self) -> None:
        online_part_same_lecturer = replace(self.parts[3], lecturer_index=0)
        problem = replace(
            self.problem,
            teaching_parts=self.parts[:3] + (online_part_same_lecturer,),
        )
        online_early = self.valid_options[3]
        online_middle = replace(online_early, start_period=4, end_period=6)
        domains = (
            (self.valid_options[0],),
            (self.valid_options[1],),
            (self.valid_options[2],),
            (online_early, online_middle),
        )

        result = decode_vector(
            problem,
            domains,
            (0.0, 0.0, 0.0, 0.25),
            max_decode_nodes=20,
        )

        self.assertEqual(result.status, DecodeStatus.SUCCESS)
        self.assertEqual(result.selected_option_indices[3], 1)
        self.assertTrue(validate_timetable(problem, result.selected_options).is_valid)


if __name__ == "__main__":
    unittest.main()
