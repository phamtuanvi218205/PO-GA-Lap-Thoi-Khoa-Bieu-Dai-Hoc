"""Sinh ba snapshot D109 để đánh giá khả năng mở rộng của bài toán lịch.

Ba profile dùng cùng học kỳ, giảng viên, phòng, availability và cấu hình ràng
buộc. Chỉ số lớp học phần, gene và occurrence tăng dần; nhờ giữ nguyên quỹ tài
nguyên, profile lớn đồng thời tạo áp lực cạnh tranh cao hơn profile nhỏ.

Script này chỉ chuẩn bị dữ liệu và manifest. Nó không chạy Greedy, GA, PO hay
GA–PO; benchmark được thực hiện ở một bước riêng.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gapo_timetabling.core.snapshot import canonical_json, checksum_json


DEMO_DATA_DIRECTORY = Path(__file__).resolve().parent
BASE_SNAPSHOT_PATH = DEMO_DATA_DIRECTORY / "benchmark_snapshot_2027_HK1.json"
OUTPUT_DIRECTORY = DEMO_DATA_DIRECTORY / "scalability"
MANIFEST_PATH = OUTPUT_DIRECTORY / "manifest.json"


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """Mô tả một lớp cần giữ hoặc nhân bản từ snapshot gốc."""

    source_section_code: str
    section_code: str
    section_name: str | None = None
    expected_enrollment: int | None = None


@dataclass(frozen=True, slots=True)
class ScaleProfile:
    """Cấu hình xác định cho một mức kích thước."""

    code: str
    scenario_id: int
    sections: tuple[SectionSpec, ...]
    lecturer_max_teaching_periods: int | None = None


BASE_SECTION_CODES = (
    "AI01",
    "DB01",
    "JAVA01",
    "JAVA02",
    "NET01",
    "WEB01",
    "WEB02",
)

PROFILES = (
    ScaleProfile(
        code="small",
        scenario_id=201,
        sections=tuple(
            SectionSpec(code, code)
            for code in ("AI01", "JAVA01", "WEB01")
        ),
    ),
    ScaleProfile(
        code="medium",
        scenario_id=202,
        sections=tuple(
            SectionSpec(code, code)
            for code in BASE_SECTION_CODES
        ),
    ),
    ScaleProfile(
        code="large",
        scenario_id=203,
        sections=(
            *(SectionSpec(code, code) for code in BASE_SECTION_CODES),
            SectionSpec(
                "AI01",
                "AI02",
                "Trí tuệ nhân tạo 02",
                45,
            ),
            SectionSpec(
                "DB01",
                "DB02",
                "Cơ sở dữ liệu 02",
                45,
            ),
            SectionSpec(
                "NET01",
                "NET02",
                "Mạng máy tính 02",
                45,
            ),
        ),
        lecturer_max_teaching_periods=150,
    ),
)


def _load_base_snapshot() -> dict[str, Any]:
    """Đọc snapshot D109 làm nguồn xác định cho ba profile."""

    return json.loads(BASE_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _replace_code_prefix(value: str, old: str, new: str) -> str:
    """Đổi tiền tố mã lớp mà không sửa phần hậu tố LT/TH của đối tượng."""

    if value.startswith(old):
        return new + value[len(old):]
    return value


def build_profile_payload(
    base: dict[str, Any],
    profile: ScaleProfile,
) -> dict[str, Any]:
    """Dựng một snapshot có index liên tục và ID không trùng."""

    sections_by_code = {
        item["section_code"]: item
        for item in base["course_sections"]
    }
    parts_by_section: dict[str, list[dict[str, Any]]] = {}
    for part in base["teaching_parts"]:
        parts_by_section.setdefault(part["section_code"], []).append(part)
    for parts in parts_by_section.values():
        parts.sort(key=lambda item: item["teaching_part_index"])

    plans_by_part_index = {
        item["teaching_part_index"]: item
        for item in base["teaching_plans"]
    }
    sessions_by_plan_id: dict[int, list[dict[str, Any]]] = {}
    for session in base["class_sessions"]:
        sessions_by_plan_id.setdefault(
            session["teaching_plan_id"],
            [],
        ).append(session)
    for sessions in sessions_by_plan_id.values():
        sessions.sort(key=lambda item: item["session_number"])

    sections: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    scenario_items: list[dict[str, int]] = []

    next_part_id = profile.scenario_id * 1_000
    next_plan_id = profile.scenario_id * 10_000
    next_session_id = profile.scenario_id * 100_000

    for spec in profile.sections:
        source_section = sections_by_code[spec.source_section_code]
        section = deepcopy(source_section)
        section["section_code"] = spec.section_code
        if spec.section_name is not None:
            section["section_name"] = spec.section_name
        if spec.expected_enrollment is not None:
            section["expected_enrollment"] = spec.expected_enrollment
        sections.append(section)

        for source_part in parts_by_section[spec.source_section_code]:
            part_index = len(parts)
            part = deepcopy(source_part)
            part["teaching_part_index"] = part_index
            part["teaching_part_id"] = next_part_id + part_index + 1
            part["section_code"] = spec.section_code
            part["part_code"] = _replace_code_prefix(
                source_part["part_code"],
                spec.source_section_code,
                spec.section_code,
            )
            parts.append(part)

            source_plan = plans_by_part_index[
                source_part["teaching_part_index"]
            ]
            plan_id = next_plan_id + part_index + 1
            plan = deepcopy(source_plan)
            plan["teaching_plan_id"] = plan_id
            plan["teaching_part_index"] = part_index
            plan["plan_code"] = (
                f"SCALE_{profile.code.upper()}_{part['part_code']}_P01"
            )
            plans.append(plan)
            scenario_items.append({
                "teaching_part_index": part_index,
                "teaching_plan_id": plan_id,
            })

            for source_session in sessions_by_plan_id[
                source_plan["teaching_plan_id"]
            ]:
                session_index = len(sessions)
                session = deepcopy(source_session)
                session["class_session_id"] = next_session_id + session_index + 1
                session["session_index"] = session_index
                session["teaching_plan_id"] = plan_id
                sessions.append(session)

    used_course_codes = {item["course_code"] for item in sections}
    payload = deepcopy(base)
    payload["courses"] = [
        deepcopy(item)
        for item in base["courses"]
        if item["course_code"] in used_course_codes
    ]
    payload["course_sections"] = sections
    payload["teaching_parts"] = parts
    payload["teaching_plans"] = plans
    payload["class_sessions"] = sessions
    payload["lecturer_course_capabilities"] = [
        deepcopy(item)
        for item in base["lecturer_course_capabilities"]
        if item["course_code"] in used_course_codes
    ]
    if profile.lecturer_max_teaching_periods is not None:
        for lecturer in payload["lecturers"]:
            lecturer["max_teaching_periods"] = (
                profile.lecturer_max_teaching_periods
            )
    payload["scenario"] = {
        "scenario_id": profile.scenario_id,
        "scenario_code": f"SCALE_{profile.code.upper()}_2027_HK1_D109",
        "term_code": base["term"]["term_code"],
        "scope_type": "FULL_TERM",
        "status": "LOCKED",
        "items": scenario_items,
    }
    return payload


def describe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Tạo metadata không cần chạy optimizer."""

    schedule_groups = {
        (item["teaching_plan_id"], item["stability_group_no"])
        for item in payload["class_sessions"]
    }
    assignment_gene_count = len(payload["course_sections"])
    schedule_gene_count = len(schedule_groups)
    total_required_periods = sum(
        item["total_periods"] for item in payload["teaching_parts"]
    )
    total_lecturer_capacity = sum(
        item["max_teaching_periods"]
        for item in payload["lecturers"]
        if item["max_teaching_periods"] is not None
    )
    return {
        "section_count": len(payload["course_sections"]),
        "teaching_part_count": len(payload["teaching_parts"]),
        "class_session_count": len(payload["class_sessions"]),
        "assignment_gene_count": assignment_gene_count,
        "schedule_gene_count": schedule_gene_count,
        "dimension": assignment_gene_count + schedule_gene_count,
        "lecturer_count": len(payload["lecturers"]),
        "location_count": len(payload["locations"]),
        "total_required_periods": total_required_periods,
        "total_lecturer_capacity": total_lecturer_capacity,
        "load_pressure_ratio": round(
            total_required_periods / total_lecturer_capacity,
            6,
        ),
        "snapshot_sha256": checksum_json(payload),
    }


def generate_all(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Ghi ba snapshot và manifest, trả metadata để test hoặc CLI sử dụng."""

    base = _load_base_snapshot()
    output_directory.mkdir(parents=True, exist_ok=True)
    profiles_metadata: list[dict[str, Any]] = []

    for profile in PROFILES:
        payload = build_profile_payload(base, profile)
        output_path = output_directory / (
            f"timetable_scale_{profile.code}_2027_HK1.json"
        )
        output_path.write_text(canonical_json(payload), encoding="utf-8")
        profiles_metadata.append({
            "profile": profile.code,
            "file": output_path.name,
            **describe_payload(payload),
        })

    manifest = {
        "schema_version": "timetable-scalability-fixtures.v1",
        "source_snapshot": BASE_SNAPSHOT_PATH.name,
        "resource_policy": (
            "Giữ nguyên sáu giảng viên, năm địa điểm và availability; tăng số "
            "lớp để tăng kích thước và cạnh tranh. Profile lớn nâng trần tải "
            "mỗi giảng viên từ 120 lên 150 tiết để vẫn tồn tại lịch hợp lệ, "
            "nhưng tỷ lệ tổng tiết/trần tải vẫn cao hơn profile vừa."
        ),
        "benchmark_executed": False,
        "profiles": profiles_metadata,
    }
    (output_directory / MANIFEST_PATH.name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    """Sinh dữ liệu và in manifest; không khởi chạy thuật toán tối ưu."""

    manifest = generate_all()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
