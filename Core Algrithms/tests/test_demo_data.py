"""Regression tests for the resource-constrained demonstration snapshot."""

import unittest
from pathlib import Path

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    PopulationInitializationStatus,
    initialize_population,
)
from gapo_timetabling.snapshot import (
    SnapshotPreparationStatus,
    prepare_snapshot_for_optimization,
)


SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "demo_data"
    / "large_timetable_snapshot.json"
)


class TestResourceConstrainedDemoData(unittest.TestCase):
    """Protect the intended scale, scarcity, and feasibility of demo data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prepared = prepare_snapshot_for_optimization(SNAPSHOT_PATH)

    def test_snapshot_is_large_and_resource_constrained(self) -> None:
        problem = self.prepared.problem
        domain_sizes = tuple(map(len, self.prepared.option_domains))

        self.assertEqual(self.prepared.status, SnapshotPreparationStatus.READY)
        self.assertEqual(problem.dimension, 108)
        self.assertEqual(len(problem.course_sections), 9)
        self.assertEqual(len(problem.lecturers), 4)
        self.assertEqual(len(problem.rooms), 4)
        self.assertEqual(min(domain_sizes), 2)
        self.assertLessEqual(max(domain_sizes), 13)
        self.assertEqual(sum(domain_sizes), 704)

    def test_snapshot_has_a_hard_feasible_timetable(self) -> None:
        """A difficult fixture must not silently become an impossible fixture."""

        initialization = initialize_population(
            self.prepared.problem,
            self.prepared.option_domains,
            population_size=1,
            max_initialization_attempts=20,
            seed=42,
            evaluation_config=CandidateEvaluationConfig(
                max_decode_nodes=200_000,
                enable_repair=True,
                max_repair_attempts=3,
            ),
        )

        self.assertEqual(
            initialization.status,
            PopulationInitializationStatus.SUCCESS,
        )
        validation = validate_timetable(
            self.prepared.problem,
            initialization.individuals[0].selected_options,
        )
        self.assertTrue(validation.is_valid)


if __name__ == "__main__":
    unittest.main()
