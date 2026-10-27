"""Điểm vào dòng lệnh của ứng dụng xếp thời khóa biểu thuần Python."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from .database import connect_sql_server, transaction
from ..core.models import OptimizationAlgorithm, ScenarioScopeType
from .optimization_service import OptimizationRunConfig, OptimizationRunService
from .planning import AutomaticScenarioRequest
from .planning_persistence import TeachingPlanPersistenceService
from .scenario_service import PlanningScenarioOrchestrationService
from .snapshot_builder import ProblemInstanceSnapshotBuilder
from .timetable_export import TimetableExportService
from .timetable_excel import TimetableExcelExportService
from .timetable_query import TimetableQueryFilters, TimetableQueryService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gapo-timetabling",
        description=(
            "Chuẩn bị dữ liệu, chạy GA/PO/GA-PO và xuất lịch bằng Python."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plans = commands.add_parser("generate-plans", help="Sinh plan cho một TeachingPart.")
    plans.add_argument("teaching_part_id", type=int)

    scenarios = commands.add_parser(
        "create-scenarios", help="Tạo và khóa các scenario ứng viên."
    )
    scenarios.add_argument("term_code")
    scenarios.add_argument("--scope", choices=("FULL_TERM", "SUBSET"), default="FULL_TERM")
    scenarios.add_argument("--part-id", type=int, action="append", default=[])
    scenarios.add_argument("--max-candidates", type=int, default=10)

    snapshot = commands.add_parser("build-snapshot", help="Xuất snapshot v2 của scenario.")
    snapshot.add_argument("scenario_id", type=int)
    snapshot.add_argument("--output", type=Path, required=True)

    optimize = commands.add_parser("optimize", help="Chạy và lưu một lần tối ưu.")
    optimize.add_argument("scenario_id", type=int)
    optimize.add_argument("--algorithm", choices=("GA", "PO", "GA_PO"), default="GA_PO")
    optimize.add_argument("--population-size", type=int, default=60)
    optimize.add_argument("--max-fe", type=int, default=30_060)
    optimize.add_argument("--seed", type=int, default=42)
    optimize.add_argument("--max-initialization-attempts", type=int, default=6_000)
    optimize.add_argument("--max-offspring-attempts", type=int, default=5)

    export = commands.add_parser(
        "export-schedule",
        help="Xuất lịch đã lưu của một run COMPLETED thành CSV.",
    )
    export.add_argument("run_id", type=int)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--lecturer-code")
    export.add_argument("--section-code")
    export.add_argument("--term-code")
    export.add_argument("--week-number", type=int)

    export_excel = commands.add_parser(
        "export-schedule-xlsx",
        help="Xuất lịch đã lưu của một run COMPLETED thành Excel.",
    )
    export_excel.add_argument("run_id", type=int)
    export_excel.add_argument("--output", type=Path, required=True)
    export_excel.add_argument("--lecturer-code")
    export_excel.add_argument("--section-code")
    export_excel.add_argument("--term-code")
    export_excel.add_argument("--week-number", type=int)

    serve = commands.add_parser("serve-api", help="Khởi chạy HTTP API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--http-workers",
        type=int,
        default=1,
        help="Số Uvicorn process phục vụ HTTP.",
    )
    serve.add_argument(
        "--run-workers",
        type=int,
        default=2,
        help="Số optimization run tối đa được xử lý đồng thời.",
    )
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)

    if args.command == "generate-plans":
        with transaction() as connection:
            plans = TeachingPlanPersistenceService(connection).ensure_current_plans(
                args.teaching_part_id
            )
        _print_json({
            "teaching_part_id": args.teaching_part_id,
            "plan_count": len(plans),
            "plans": [
                {
                    "teaching_plan_id": plan.teaching_plan_id,
                    "plan_code": plan.plan_code,
                    "candidate_rank": plan.candidate_rank,
                    "status": plan.status.value,
                }
                for plan in plans
            ],
        })
        return 0

    if args.command == "create-scenarios":
        request = AutomaticScenarioRequest(
            term_code=args.term_code,
            scope_type=ScenarioScopeType(args.scope),
            teaching_part_ids=frozenset(args.part_id),
            max_scenario_candidates=args.max_candidates,
        )
        with transaction() as connection:
            scenarios = PlanningScenarioOrchestrationService(
                connection
            ).create_and_lock_candidates(request)
        _print_json({
            "scenario_count": len(scenarios),
            "scenarios": [
                {
                    "scenario_id": scenario.scenario_id,
                    "scenario_code": scenario.scenario_code,
                    "candidate_rank": scenario.candidate_rank,
                    "status": scenario.status.value,
                    "note": scenario.note,
                }
                for scenario in scenarios
            ],
        })
        return 0

    if args.command == "build-snapshot":
        connection = connect_sql_server()
        try:
            built = ProblemInstanceSnapshotBuilder(connection).build(args.scenario_id)
        finally:
            connection.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(built.canonical_json + "\n", encoding="utf-8")
        _print_json({
            "scenario_id": args.scenario_id,
            "output": str(args.output.resolve()),
            "sha256": built.sha256_checksum,
        })
        return 0

    if args.command == "export-schedule":
        connection = connect_sql_server()
        try:
            filters = TimetableQueryFilters(
                lecturer_code=args.lecturer_code,
                section_code=args.section_code,
                term_code=args.term_code,
                week_number=args.week_number,
            )
            exported = TimetableExportService(
                TimetableQueryService(connection)
            ).export_run_csv(args.run_id, args.output, filters)
        finally:
            connection.close()
        _print_json({
            "run_id": args.run_id,
            "output": str(exported.output_path),
            "row_count": exported.row_count,
        })
        return 0

    if args.command == "export-schedule-xlsx":
        connection = connect_sql_server()
        try:
            filters = TimetableQueryFilters(
                lecturer_code=args.lecturer_code,
                section_code=args.section_code,
                term_code=args.term_code,
                week_number=args.week_number,
            )
            exported = TimetableExcelExportService(
                TimetableQueryService(connection)
            ).export_run_xlsx(args.run_id, args.output, filters)
        finally:
            connection.close()
        _print_json({
            "run_id": args.run_id,
            "output": str(exported.output_path),
            "row_count": exported.row_count,
        })
        return 0

    if args.command == "serve-api":
        import uvicorn

        if args.run_workers < 1:
            raise ValueError("--run-workers phải lớn hơn hoặc bằng 1.")
        if args.http_workers < 1:
            raise ValueError("--http-workers phải lớn hơn hoặc bằng 1.")
        os.environ["GAPO_RUN_WORKERS"] = str(args.run_workers)
        uvicorn.run(
            "gapo_timetabling.application.api:app",
            host=args.host,
            port=args.port,
            workers=args.http_workers,
        )
        return 0

    connection = connect_sql_server()
    try:
        persisted = OptimizationRunService(connection).run_scenario(
            args.scenario_id,
            OptimizationRunConfig(
                algorithm=OptimizationAlgorithm(args.algorithm),
                population_size=args.population_size,
                max_fitness_evaluations=args.max_fe,
                random_seed=args.seed,
                algorithm_version="python-unified-v1",
                max_initialization_attempts=args.max_initialization_attempts,
                max_offspring_attempts=args.max_offspring_attempts,
            ),
        )
    finally:
        connection.close()
    _print_json({
        "run_id": persisted.run_id,
        "status": persisted.status,
        "algorithm": args.algorithm,
    })
    return 0 if persisted.status == "COMPLETED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
