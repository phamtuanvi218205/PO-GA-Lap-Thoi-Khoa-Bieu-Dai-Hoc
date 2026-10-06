"""Đọc snapshot Java và chuẩn bị đầu vào bất biến cho core tối ưu.

Java chịu trách nhiệm chụp dữ liệu của một ``PlanningScenario`` đã khóa thành
JSON. Module này là biên hợp đồng ở phía Python: kiểm tra version/checksum,
chuyển JSON thành ``ProblemInstance``, sinh miền option và tạo bảng ánh xạ
gene–option có thể lưu cùng một lần chạy.

Module không chạy GA, PO hoặc GA–PO. Nếu một buổi không có option, lỗi được
trả ngay ở bước preflight với trạng thái ``NO_OPTION`` để optimizer không phải
nhận một đề bài chắc chắn không thể xử lý.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .decoder import explain_empty_domain
from .encoder import build_option_domains
from .models import (
    AcademicTerm,
    AcademicTermStatus,
    AllowedPeriodBlock,
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    CampusTravelTime,
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


SNAPSHOT_SCHEMA_VERSION = "problem-instance.v1"
MAPPING_SCHEMA_VERSION = "gene-option-mapping.v1"


class SnapshotContractError(ValueError):
    """Cho biết JSON vi phạm hợp đồng trao đổi Java–Python."""


class SnapshotPreparationStatus(str, Enum):
    """Kết quả kiểm tra trước khi cho phép optimizer bắt đầu."""

    READY = "READY"
    NO_OPTION = "NO_OPTION"


@dataclass(frozen=True, slots=True)
class NoOptionIssue:
    """Một buổi không có bất kỳ vị trí ngày–tiết–địa điểm hợp lệ nào."""

    session_index: int
    class_session_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class PreparedSnapshot:
    """Đầu ra hoàn chỉnh của bước nạp snapshot và encoder preflight."""

    status: SnapshotPreparationStatus
    problem: ProblemInstance
    snapshot_checksum: str
    option_domains: tuple[tuple[SessionOption, ...], ...]
    gene_option_mapping: Mapping[str, Any] | None
    gene_option_mapping_json: str | None
    gene_option_mapping_checksum: str | None
    no_option_issues: tuple[NoOptionIssue, ...]

    @property
    def is_ready(self) -> bool:
        """Chỉ READY mới được chuyển tiếp sang GA, PO hoặc GA–PO."""

        return self.status == SnapshotPreparationStatus.READY


def canonical_json(value: Mapping[str, Any]) -> str:
    """Chuẩn hóa JSON để Java và Python có thể đối chiếu SHA-256.

    Khóa object được sắp xếp, không chèn khoảng trắng và giữ nguyên Unicode.
    Danh sách không bị sắp xếp lại vì thứ tự của session/location chính là một
    phần của hợp đồng chỉ số nén.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def checksum_json(value: Mapping[str, Any]) -> str:
    """Tính SHA-256 chữ thường từ biểu diễn JSON canonical."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _load_json_object(
    source: str | bytes | Path | Mapping[str, Any],
) -> dict[str, Any]:
    """Đọc object từ mapping, chuỗi JSON, bytes hoặc đường dẫn file."""

    if isinstance(source, Mapping):
        return dict(source)

    if isinstance(source, Path):
        raw_text = source.read_text(encoding="utf-8")
    elif isinstance(source, bytes):
        raw_text = source.decode("utf-8")
    elif isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{"):
            raw_text = source
        else:
            raw_text = Path(source).read_text(encoding="utf-8")
    else:
        raise TypeError("Snapshot phải là mapping, JSON, bytes hoặc đường dẫn file.")

    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise SnapshotContractError("Gốc snapshot JSON phải là một object.")
    return parsed


def _required(item: Mapping[str, Any], field: str) -> Any:
    """Đọc trường bắt buộc và tạo lỗi có tên trường rõ ràng."""

    if field not in item:
        raise SnapshotContractError(f"Snapshot thiếu trường bắt buộc '{field}'.")
    return item[field]


def _date(value: str | None) -> date | None:
    """Chuyển ngày ISO yyyy-MM-dd; giữ None cho trường không áp dụng."""

    return None if value is None else date.fromisoformat(value)


def _time(value: str) -> time:
    """Chuyển giờ ISO do Java phát ra thành ``datetime.time``."""

    return time.fromisoformat(value)


def _equipment(items: list[Mapping[str, Any]]) -> tuple[tuple[str, int], ...]:
    """Đổi danh sách thiết bị JSON sang tuple bất biến của core."""

    return tuple(
        (str(_required(item, "equipment_code")), int(_required(item, "quantity")))
        for item in items
    )


def _availability(item: Mapping[str, Any]) -> AvailabilityWindow:
    """Dựng một availability cho giảng viên hoặc phòng."""

    return AvailabilityWindow(
        resource_index=int(_required(item, "resource_index")),
        scope_type=AvailabilityScopeType(_required(item, "scope_type")),
        start_period=int(_required(item, "start_period")),
        end_period=int(_required(item, "end_period")),
        availability_type=AvailabilityType(_required(item, "availability_type")),
        calendar_date=_date(item.get("calendar_date")),
        iso_weekday=(
            None if item.get("iso_weekday") is None else int(item["iso_weekday"])
        ),
        preference_weight=(
            None
            if item.get("preference_weight") is None
            else float(item["preference_weight"])
        ),
    )


def load_problem_instance_snapshot(
    source: str | bytes | Path | Mapping[str, Any],
    *,
    expected_checksum: str | None = None,
) -> tuple[ProblemInstance, str]:
    """Nạp snapshot v1 thành ``ProblemInstance`` và trả checksum đã tính.

    ``expected_checksum`` thường lấy từ ``OptimizationRun``. Nếu checksum
    không khớp, hàm dừng ngay vì dữ liệu đã bị thay đổi hoặc truyền thiếu.
    """

    payload = _load_json_object(source)
    schema_version = _required(payload, "schema_version")
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotContractError(
            "Không hỗ trợ snapshot schema version "
            f"'{schema_version}'; cần '{SNAPSHOT_SCHEMA_VERSION}'."
        )

    actual_checksum = checksum_json(payload)
    if expected_checksum is not None and actual_checksum != expected_checksum.lower():
        raise SnapshotContractError(
            "Checksum snapshot không khớp; dữ liệu không còn đúng bản đã khóa."
        )

    term_data = _required(payload, "term")
    scenario_data = _required(payload, "scenario")

    locations = []
    for item in _required(payload, "locations"):
        common = dict(
            location_index=int(_required(item, "location_index")),
            location_id=int(_required(item, "location_id")),
            location_code=str(_required(item, "location_code")),
            location_name=str(_required(item, "location_name")),
            active=bool(_required(item, "active")),
        )
        location_type = LocationType(_required(item, "location_type"))
        if location_type == LocationType.PHYSICAL_ROOM:
            locations.append(
                Room(
                    **common,
                    campus_code=str(_required(item, "campus_code")),
                    room_type=RoomType(_required(item, "room_type")),
                    capacity=(
                        None
                        if item.get("capacity") is None
                        else int(item["capacity"])
                    ),
                    equipment_quantities=_equipment(item.get("equipment_quantities", [])),
                )
            )
        elif location_type == LocationType.ONLINE:
            locations.append(
                OnlineLocation(
                    **common,
                    platform_name=str(_required(item, "platform_name")),
                )
            )
        else:  # pragma: no cover - Enum đã bảo vệ, giữ nhánh để diễn đạt hợp đồng.
            raise SnapshotContractError(f"Loại địa điểm không hỗ trợ: {location_type}.")

    problem = ProblemInstance(
        term=AcademicTerm(
            term_code=str(_required(term_data, "term_code")),
            term_name=str(_required(term_data, "term_name")),
            start_date=_date(_required(term_data, "start_date")),
            end_date=_date(_required(term_data, "end_date")),
            status=AcademicTermStatus(_required(term_data, "status")),
        ),
        scenario=PlanningScenario(
            scenario_id=int(_required(scenario_data, "scenario_id")),
            scenario_code=str(_required(scenario_data, "scenario_code")),
            term_code=str(_required(scenario_data, "term_code")),
            scope_type=ScenarioScopeType(_required(scenario_data, "scope_type")),
            status=PlanningScenarioStatus(_required(scenario_data, "status")),
            items=tuple(
                PlanningScenarioItem(
                    teaching_part_index=int(_required(item, "teaching_part_index")),
                    teaching_plan_id=int(_required(item, "teaching_plan_id")),
                )
                for item in _required(scenario_data, "items")
            ),
        ),
        weeks=tuple(
            TermWeek(
                week_number=int(_required(item, "week_number")),
                start_date=_date(_required(item, "start_date")),
                end_date=_date(_required(item, "end_date")),
            )
            for item in _required(payload, "weeks")
        ),
        teaching_dates=tuple(
            TeachingDate(
                calendar_date=_date(_required(item, "calendar_date")),
                week_number=int(_required(item, "week_number")),
                iso_weekday=int(_required(item, "iso_weekday")),
                status=DateStatus(_required(item, "status")),
            )
            for item in _required(payload, "teaching_dates")
        ),
        time_periods=tuple(
            TimePeriod(
                period_number=int(_required(item, "period_number")),
                start_time=_time(_required(item, "start_time")),
                end_time=_time(_required(item, "end_time")),
                session_type=SessionType(_required(item, "session_type")),
            )
            for item in _required(payload, "time_periods")
        ),
        allowed_period_blocks=tuple(
            AllowedPeriodBlock(
                start_period=int(_required(item, "start_period")),
                duration_periods=int(_required(item, "duration_periods")),
            )
            for item in _required(payload, "allowed_period_blocks")
        ),
        teaching_duration_rules=tuple(
            TeachingDurationRule(
                part_type=PartType(_required(item, "part_type")),
                duration_periods=int(_required(item, "duration_periods")),
                is_standard=bool(_required(item, "standard")),
            )
            for item in _required(payload, "teaching_duration_rules")
        ),
        locations=tuple(locations),
        lecturers=tuple(
            Lecturer(
                lecturer_index=int(_required(item, "lecturer_index")),
                lecturer_code=str(_required(item, "lecturer_code")),
                full_name=str(_required(item, "full_name")),
                home_campus_code=item.get("home_campus_code"),
            )
            for item in _required(payload, "lecturers")
        ),
        courses=tuple(
            Course(
                course_code=str(_required(item, "course_code")),
                course_name=str(_required(item, "course_name")),
            )
            for item in _required(payload, "courses")
        ),
        course_sections=tuple(
            CourseSection(
                section_code=str(_required(item, "section_code")),
                course_code=str(_required(item, "course_code")),
                section_name=str(_required(item, "section_name")),
                expected_enrollment=(
                    None
                    if item.get("expected_enrollment") is None
                    else int(item["expected_enrollment"])
                ),
            )
            for item in _required(payload, "course_sections")
        ),
        teaching_parts=tuple(
            TeachingPart(
                teaching_part_index=int(_required(item, "teaching_part_index")),
                teaching_part_id=int(_required(item, "teaching_part_id")),
                part_code=str(_required(item, "part_code")),
                section_code=str(_required(item, "section_code")),
                part_type=PartType(_required(item, "part_type")),
                lecturer_index=int(_required(item, "lecturer_index")),
                total_periods=int(_required(item, "total_periods")),
                required_location_type=LocationType(
                    _required(item, "required_location_type")
                ),
                required_room_type=(
                    None
                    if item.get("required_room_type") is None
                    else RoomType(item["required_room_type"])
                ),
                required_equipment=_equipment(item.get("required_equipment", [])),
            )
            for item in _required(payload, "teaching_parts")
        ),
        teaching_plans=tuple(
            TeachingPlan(
                teaching_plan_id=int(_required(item, "teaching_plan_id")),
                plan_code=str(_required(item, "plan_code")),
                teaching_part_index=int(_required(item, "teaching_part_index")),
                status=TeachingPlanStatus(_required(item, "status")),
                allows_intensive=bool(_required(item, "allows_intensive")),
            )
            for item in _required(payload, "teaching_plans")
        ),
        class_sessions=tuple(
            ClassSession(
                session_index=int(_required(item, "session_index")),
                class_session_id=int(_required(item, "class_session_id")),
                teaching_plan_id=int(_required(item, "teaching_plan_id")),
                session_number=int(_required(item, "session_number")),
                stability_group_no=int(_required(item, "stability_group_no")),
                week_number=int(_required(item, "week_number")),
                duration_periods=int(_required(item, "duration_periods")),
                required_location_type=LocationType(
                    _required(item, "required_location_type")
                ),
            )
            for item in _required(payload, "class_sessions")
        ),
        lecturer_availabilities=tuple(
            _availability(item)
            for item in _required(payload, "lecturer_availabilities")
        ),
        room_availabilities=tuple(
            _availability(item)
            for item in _required(payload, "room_availabilities")
        ),
        campus_travel_times=tuple(
            CampusTravelTime(
                from_campus_code=str(_required(item, "from_campus_code")),
                to_campus_code=str(_required(item, "to_campus_code")),
                travel_minutes=int(_required(item, "travel_minutes")),
            )
            for item in _required(payload, "campus_travel_times")
        ),
        constraint_settings=tuple(
            ConstraintSetting(
                constraint_code=str(_required(item, "constraint_code")),
                constraint_type=ConstraintType(_required(item, "constraint_type")),
                priority_tier=int(_required(item, "priority_tier")),
                weight=None if item.get("weight") is None else float(item["weight"]),
                enabled=bool(_required(item, "enabled")),
            )
            for item in _required(payload, "constraint_settings")
        ),
    )
    return problem, actual_checksum


def build_gene_option_mapping(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    snapshot_checksum: str,
) -> dict[str, Any]:
    """Tạo bảng giải thích chính xác mỗi gene có những option nào.

    Option được ghi theo đúng thứ tự encoder. Vì vậy ``option_index`` là chỉ
    số mà random-key và decoder sử dụng, không phải ID tự phát trong database.
    """

    if len(option_domains) != problem.dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")

    locations_by_index = {
        location.location_index: location
        for location in problem.locations
    }
    genes = []
    for session, domain in zip(problem.class_sessions, option_domains):
        options = []
        for option_index, option in enumerate(domain):
            location = locations_by_index[option.location_index]
            options.append(
                {
                    "option_index": option_index,
                    "location_index": option.location_index,
                    "location_id": location.location_id,
                    "location_code": location.location_code,
                    "teaching_date": option.teaching_date.isoformat(),
                    "start_period": option.start_period,
                    "end_period": option.end_period,
                }
            )

        genes.append(
            {
                "gene_index": session.session_index,
                "class_session_id": session.class_session_id,
                "options": options,
            }
        )

    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "snapshot_checksum": snapshot_checksum,
        "dimension": problem.dimension,
        "genes": genes,
    }


def prepare_snapshot_for_optimization(
    source: str | bytes | Path | Mapping[str, Any],
    *,
    expected_checksum: str | None = None,
) -> PreparedSnapshot:
    """Nạp snapshot, chạy encoder preflight và dựng mapping nếu khả thi."""

    problem, snapshot_checksum = load_problem_instance_snapshot(
        source,
        expected_checksum=expected_checksum,
    )
    option_domains = build_option_domains(problem)

    issues = tuple(
        NoOptionIssue(
            session_index=session.session_index,
            class_session_id=session.class_session_id,
            reason=explain_empty_domain(problem, session),
        )
        for session, domain in zip(problem.class_sessions, option_domains)
        if not domain
    )
    if issues:
        return PreparedSnapshot(
            status=SnapshotPreparationStatus.NO_OPTION,
            problem=problem,
            snapshot_checksum=snapshot_checksum,
            option_domains=option_domains,
            gene_option_mapping=None,
            gene_option_mapping_json=None,
            gene_option_mapping_checksum=None,
            no_option_issues=issues,
        )

    mapping = build_gene_option_mapping(
        problem,
        option_domains,
        snapshot_checksum,
    )
    mapping_json = canonical_json(mapping)
    return PreparedSnapshot(
        status=SnapshotPreparationStatus.READY,
        problem=problem,
        snapshot_checksum=snapshot_checksum,
        option_domains=option_domains,
        gene_option_mapping=mapping,
        gene_option_mapping_json=mapping_json,
        gene_option_mapping_checksum=sha256(mapping_json.encode("utf-8")).hexdigest(),
        no_option_issues=(),
    )
