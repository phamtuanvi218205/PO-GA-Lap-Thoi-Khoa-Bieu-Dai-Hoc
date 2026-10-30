"""Hợp đồng và dịch vụ nhập dữ liệu nguồn của một học kỳ.

Hai kênh nhập liệu của ứng dụng (biểu mẫu HTTP và workbook Excel) phải tạo ra
cùng một :class:`SemesterInputBundle`.  Module này là nơi duy nhất kiểm tra
quan hệ chéo và ghi dữ liệu vào SQL Server; vì vậy quy tắc nghiệp vụ không bị
nhân đôi giữa giao diện nhập tay và importer.

Bundle chỉ chứa dữ liệu biết trước khi xếp lịch.  TeachingPlan, ClassSession,
SessionOption, snapshot và vector tối ưu do pipeline hiện có tự sinh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from .teaching_part_generation import TeachingPartGenerator


Code20 = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_.-]+$")]
Code30 = Annotated[str, Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$")]


class AcademicTermInput(BaseModel):
    term_code: Code20
    term_name: str = Field(min_length=1, max_length=150)
    start_date: date
    number_of_weeks: int = Field(ge=1, le=30)
    status: Literal["PLANNING", "ACTIVE", "CLOSED"] = "PLANNING"

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.number_of_weeks * 7 - 1)

    @model_validator(mode="after")
    def require_complete_monday_to_sunday_weeks(self) -> "AcademicTermInput":
        if self.start_date.isoweekday() != 1:
            raise ValueError("start_date phải là thứ Hai đầu tiên của tuần học.")
        return self


class CampusInput(BaseModel):
    campus_code: Code20
    campus_name: str = Field(min_length=1, max_length=150)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class CourseInput(BaseModel):
    course_code: Code20
    course_name: str = Field(min_length=1, max_length=200)
    credits: Decimal | None = Field(default=None, gt=0)
    is_active: bool = True


class LecturerInput(BaseModel):
    lecturer_code: Code20
    full_name: str = Field(min_length=1, max_length=150)
    email: str | None = Field(default=None, max_length=150)
    home_campus_code: Code20 | None = None
    max_teaching_periods: int | None = Field(default=None, gt=0)
    is_active: bool = True


class LecturerCapabilityInput(BaseModel):
    lecturer_code: Code20
    course_code: Code20
    can_teach_lecture: bool = False
    can_teach_practice: bool = False
    suitability_score: Decimal = Field(default=Decimal("1"), ge=0, le=1)

    @model_validator(mode="after")
    def require_supported_part_type(self) -> "LecturerCapabilityInput":
        if not self.can_teach_lecture and not self.can_teach_practice:
            raise ValueError("Năng lực phải cho phép ít nhất lý thuyết hoặc thực hành.")
        return self


class RoomInput(BaseModel):
    room_code: Code30
    room_name: str = Field(min_length=1, max_length=150)
    campus_code: Code20
    room_type: Literal["LECTURE_ROOM", "COMPUTER_LAB"]
    capacity: int | None = Field(default=None, gt=0)
    is_active: bool = True


class OnlineLocationInput(BaseModel):
    location_code: Code30
    location_name: str = Field(min_length=1, max_length=150)
    platform_name: str = Field(min_length=1, max_length=100)
    meeting_note: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class EquipmentInput(BaseModel):
    equipment_code: Code30
    equipment_name: str = Field(min_length=1, max_length=150)


class RoomEquipmentInput(BaseModel):
    room_code: Code30
    equipment_code: Code30
    quantity: int = Field(default=1, ge=1)


class CourseSectionInput(BaseModel):
    section_code: Code30
    course_code: Code20
    section_name: str | None = Field(default=None, max_length=150)
    expected_enrollment: int | None = Field(default=None, gt=0)
    status: Literal["PLANNING", "APPROVED", "CANCELLED"] = "PLANNING"


class CourseTeachingStructureInput(BaseModel):
    course_code: Code20
    part_type: Literal["LECTURE", "PRACTICE"]
    total_periods: int = Field(gt=0)
    required_location_type: Literal["PHYSICAL_ROOM", "ONLINE"] = "PHYSICAL_ROOM"
    required_room_type: Literal["LECTURE_ROOM", "COMPUTER_LAB"] | None = None
    max_sessions_per_week: int = Field(ge=1, le=7)
    allows_intensive: bool = False
    max_candidate_plans: int = Field(default=200, ge=1, le=200)
    is_active: bool = True
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_location_requirement(self) -> "CourseTeachingStructureInput":
        if self.required_location_type == "PHYSICAL_ROOM" and self.required_room_type is None:
            raise ValueError("Cấu trúc học tại phòng vật lý phải có required_room_type.")
        if self.required_location_type == "ONLINE" and self.required_room_type is not None:
            raise ValueError("Cấu trúc học trực tuyến không nhận required_room_type.")
        return self


class CourseTeachingStructureEquipmentInput(BaseModel):
    course_code: Code20
    part_type: Literal["LECTURE", "PRACTICE"]
    equipment_code: Code30
    minimum_quantity: int = Field(default=1, ge=1)


class LecturerAvailabilityInput(BaseModel):
    lecturer_code: Code20
    scope_type: Literal["DATE", "WEEKDAY"]
    calendar_date: date | None = None
    iso_weekday: int | None = Field(default=None, ge=1, le=7)
    start_period: int = Field(ge=1, le=16)
    end_period: int = Field(ge=1, le=16)
    availability_type: Literal["UNAVAILABLE", "DISCOURAGED", "PREFERRED"]
    preference_weight: Decimal | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_scope_and_weight(self) -> "LecturerAvailabilityInput":
        _validate_availability_scope(self.scope_type, self.calendar_date, self.iso_weekday)
        if self.end_period < self.start_period:
            raise ValueError("end_period phải lớn hơn hoặc bằng start_period.")
        if self.availability_type == "UNAVAILABLE" and self.preference_weight is not None:
            raise ValueError("UNAVAILABLE không nhận preference_weight.")
        if self.availability_type != "UNAVAILABLE" and self.preference_weight is None:
            raise ValueError("PREFERRED/DISCOURAGED phải có preference_weight.")
        return self


class RoomAvailabilityInput(BaseModel):
    room_code: Code30
    scope_type: Literal["DATE", "WEEKDAY"]
    calendar_date: date | None = None
    iso_weekday: int | None = Field(default=None, ge=1, le=7)
    start_period: int = Field(ge=1, le=16)
    end_period: int = Field(ge=1, le=16)
    availability_type: Literal["UNAVAILABLE", "DISCOURAGED"]
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_scope(self) -> "RoomAvailabilityInput":
        _validate_availability_scope(self.scope_type, self.calendar_date, self.iso_weekday)
        if self.end_period < self.start_period:
            raise ValueError("end_period phải lớn hơn hoặc bằng start_period.")
        return self


def _validate_availability_scope(
    scope_type: str,
    calendar_date: date | None,
    iso_weekday: int | None,
) -> None:
    if scope_type == "DATE" and (calendar_date is None or iso_weekday is not None):
        raise ValueError("Scope DATE cần calendar_date và không nhận iso_weekday.")
    if scope_type == "WEEKDAY" and (iso_weekday is None or calendar_date is not None):
        raise ValueError("Scope WEEKDAY cần iso_weekday và không nhận calendar_date.")


class SemesterInputBundle(BaseModel):
    """Gói dữ liệu chuẩn dùng chung cho nhập tay và nhập Excel."""

    model_config = ConfigDict(extra="forbid")

    term: AcademicTermInput
    campuses: list[CampusInput] = Field(default_factory=list)
    courses: list[CourseInput] = Field(default_factory=list)
    lecturers: list[LecturerInput] = Field(default_factory=list)
    lecturer_capabilities: list[LecturerCapabilityInput] = Field(default_factory=list)
    rooms: list[RoomInput] = Field(default_factory=list)
    online_locations: list[OnlineLocationInput] = Field(default_factory=list)
    equipment: list[EquipmentInput] = Field(default_factory=list)
    room_equipment: list[RoomEquipmentInput] = Field(default_factory=list)
    course_sections: list[CourseSectionInput] = Field(default_factory=list)
    course_teaching_structures: list[CourseTeachingStructureInput] = Field(
        default_factory=list
    )
    course_structure_equipment: list[CourseTeachingStructureEquipmentInput] = Field(
        default_factory=list
    )
    lecturer_availability: list[LecturerAvailabilityInput] = Field(default_factory=list)
    room_availability: list[RoomAvailabilityInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cross_references_inside_bundle(self) -> "SemesterInputBundle":
        _require_unique(self.campuses, "campus_code", "cơ sở")
        _require_unique(self.courses, "course_code", "môn học")
        _require_unique(self.lecturers, "lecturer_code", "giảng viên")
        _require_unique(self.rooms, "room_code", "phòng")
        _require_unique(self.online_locations, "location_code", "lớp trực tuyến")
        _require_unique(self.equipment, "equipment_code", "thiết bị")
        _require_unique(self.course_sections, "section_code", "lớp học phần")
        _require_unique_pair(
            self.lecturer_capabilities,
            "lecturer_code",
            "course_code",
            "năng lực giảng dạy",
        )
        _require_unique_pair(
            self.room_equipment,
            "room_code",
            "equipment_code",
            "thiết bị phòng",
        )
        _require_unique_pair(
            self.course_teaching_structures,
            "course_code",
            "part_type",
            "cấu trúc môn học",
        )
        _require_unique_triple(
            self.course_structure_equipment,
            "course_code",
            "part_type",
            "equipment_code",
            "thiết bị cấu trúc môn học",
        )
        for availability in (*self.lecturer_availability, *self.room_availability):
            if availability.calendar_date is not None and not (
                self.term.start_date <= availability.calendar_date <= self.term.end_date
            ):
                raise ValueError("Ngày availability nằm ngoài học kỳ.")
        return self


def _require_unique(items: list[Any], field: str, label: str) -> None:
    values = [str(getattr(item, field)).upper() for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"Gói dữ liệu chứa {label} trùng {field}.")


def _require_unique_pair(
    items: list[Any], first: str, second: str, label: str
) -> None:
    values = [
        (str(getattr(item, first)).upper(), str(getattr(item, second)).upper())
        for item in items
    ]
    if len(values) != len(set(values)):
        raise ValueError(f"Gói dữ liệu chứa {label} trùng ({first}, {second}).")


def _require_unique_triple(
    items: list[Any], first: str, second: str, third: str, label: str
) -> None:
    values = [
        (
            str(getattr(item, first)).upper(),
            str(getattr(item, second)).upper(),
            str(getattr(item, third)).upper(),
        )
        for item in items
    ]
    if len(values) != len(set(values)):
        raise ValueError(
            f"Gói dữ liệu chứa {label} trùng ({first}, {second}, {third})."
        )


@dataclass(frozen=True, slots=True)
class SemesterInputResult:
    term_code: str
    entity_counts: dict[str, int]


class SemesterInputPersistenceError(RuntimeError):
    """SQL Server từ chối bundle sau khi transaction đã được rollback."""


class SemesterInputNotFoundError(LookupError):
    """Không tồn tại học kỳ cần đọc để tiếp tục nhập tay."""


class SemesterInputQueryService:
    """Đọc lại dữ liệu nguồn để biểu mẫu web có thể hiển thị và chỉnh sửa."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def list_terms(self) -> tuple[dict[str, Any], ...]:
        rows = fetch_all_dicts(self._connection.cursor().execute(
            """
            SELECT term_code, term_name, start_date, end_date, status
            FROM AcademicTerm ORDER BY start_date DESC, term_code
            """
        ))
        return tuple(rows)

    def load(self, term_code: str) -> SemesterInputBundle:
        cursor = self._connection.cursor()
        term = fetch_one_dict(cursor.execute(
            """
            SELECT term.term_code, term.term_name, term.start_date, term.status,
                   COUNT(week.week_number) AS number_of_weeks
            FROM AcademicTerm AS term
            LEFT JOIN TermWeek AS week ON week.term_code = term.term_code
            WHERE term.term_code = ?
            GROUP BY term.term_code, term.term_name, term.start_date, term.status
            """,
            term_code,
        ))
        if term is None:
            raise SemesterInputNotFoundError(f"Không tồn tại học kỳ {term_code}.")
        if int(term["number_of_weeks"]) < 1:
            raise ValueError(f"Học kỳ {term_code} chưa có TermWeek.")

        payload: dict[str, Any] = {
            "term": term,
            "campuses": fetch_all_dicts(cursor.execute(
                "SELECT campus_code,campus_name,address,is_active FROM Campus ORDER BY campus_code"
            )),
            "courses": fetch_all_dicts(cursor.execute(
                "SELECT course_code,course_name,credits,is_active FROM Course ORDER BY course_code"
            )),
            "lecturers": fetch_all_dicts(cursor.execute(
                """
                SELECT lecturer_code,full_name,email,home_campus_code,
                       max_teaching_periods,is_active
                FROM Lecturer ORDER BY lecturer_code
                """
            )),
            "lecturer_capabilities": fetch_all_dicts(cursor.execute(
                """
                SELECT lecturer_code,course_code,can_teach_lecture,
                       can_teach_practice,suitability_score
                FROM LecturerCourseCapability ORDER BY lecturer_code,course_code
                """
            )),
            "rooms": fetch_all_dicts(cursor.execute(
                """
                SELECT location.location_code AS room_code,
                       location.location_name AS room_name,
                       room.campus_code,room.room_type,room.capacity,location.is_active
                FROM Room AS room
                JOIN TeachingLocation AS location ON location.location_id=room.location_id
                ORDER BY location.location_code
                """
            )),
            "online_locations": fetch_all_dicts(cursor.execute(
                """
                SELECT location.location_code,location.location_name,
                       online.platform_name,online.meeting_note,location.is_active
                FROM OnlineLocation AS online
                JOIN TeachingLocation AS location ON location.location_id=online.location_id
                ORDER BY location.location_code
                """
            )),
            "equipment": fetch_all_dicts(cursor.execute(
                "SELECT equipment_code,equipment_name FROM Equipment ORDER BY equipment_code"
            )),
            "room_equipment": fetch_all_dicts(cursor.execute(
                """
                SELECT location.location_code AS room_code,
                       item.equipment_code,item.quantity
                FROM RoomEquipment AS item
                JOIN TeachingLocation AS location ON location.location_id=item.room_location_id
                ORDER BY location.location_code,item.equipment_code
                """
            )),
            "course_sections": fetch_all_dicts(cursor.execute(
                """
                SELECT section_code,course_code,section_name,expected_enrollment,status
                FROM CourseSection WHERE term_code=? ORDER BY section_code
                """,
                term_code,
            )),
            "course_teaching_structures": fetch_all_dicts(cursor.execute(
                """
                SELECT structure.course_code,structure.part_type,
                       structure.total_periods,structure.required_location_type,
                       structure.required_room_type,structure.max_sessions_per_week,
                       structure.allows_intensive,structure.max_candidate_plans,
                       structure.is_active,structure.note
                FROM CourseTeachingStructure AS structure
                WHERE EXISTS (
                    SELECT 1 FROM CourseSection AS section
                    WHERE section.term_code=?
                      AND section.course_code=structure.course_code
                )
                ORDER BY structure.course_code,structure.part_type
                """,
                term_code,
            )),
            "course_structure_equipment": fetch_all_dicts(cursor.execute(
                """
                SELECT structure.course_code,structure.part_type,
                       item.equipment_code,item.minimum_quantity
                FROM CourseTeachingStructureRequiredEquipment AS item
                JOIN CourseTeachingStructure AS structure
                  ON structure.course_structure_id=item.course_structure_id
                WHERE EXISTS (
                    SELECT 1 FROM CourseSection AS section
                    WHERE section.term_code=?
                      AND section.course_code=structure.course_code
                )
                ORDER BY structure.course_code,structure.part_type,item.equipment_code
                """,
                term_code,
            )),
            "lecturer_availability": fetch_all_dicts(cursor.execute(
                """
                SELECT lecturer_code,scope_type,calendar_date,iso_weekday,
                       start_period,end_period,availability_type,preference_weight,note
                FROM LecturerAvailability WHERE term_code=?
                ORDER BY lecturer_code,scope_type,calendar_date,iso_weekday,start_period
                """,
                term_code,
            )),
            "room_availability": fetch_all_dicts(cursor.execute(
                """
                SELECT location.location_code AS room_code,item.scope_type,
                       item.calendar_date,item.iso_weekday,item.start_period,item.end_period,
                       item.availability_type,item.note
                FROM RoomAvailability AS item
                JOIN TeachingLocation AS location ON location.location_id=item.room_location_id
                WHERE item.term_code=?
                ORDER BY location.location_code,item.scope_type,item.calendar_date,
                         item.iso_weekday,item.start_period
                """,
                term_code,
            )),
        }
        return SemesterInputBundle.model_validate(payload)


class SemesterInputService:
    """Kiểm tra tham chiếu và ghi một bundle trong đúng một transaction."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def validate(self, bundle: SemesterInputBundle) -> None:
        """Kiểm tra mã tham chiếu bằng cả bundle và dữ liệu đang có trong DB."""

        campus_codes = {item.campus_code.upper() for item in bundle.campuses}
        course_codes = {item.course_code.upper() for item in bundle.courses}
        lecturer_codes = {item.lecturer_code.upper() for item in bundle.lecturers}
        room_codes = {item.room_code.upper() for item in bundle.rooms}
        equipment_codes = {item.equipment_code.upper() for item in bundle.equipment}
        structure_keys = {
            (item.course_code.upper(), item.part_type)
            for item in bundle.course_teaching_structures
        }

        for lecturer in bundle.lecturers:
            if lecturer.home_campus_code:
                self._require_reference(
                    lecturer.home_campus_code,
                    campus_codes,
                    "Campus",
                    "campus_code",
                    f"Giảng viên {lecturer.lecturer_code} tham chiếu cơ sở",
                )
        for room in bundle.rooms:
            self._require_reference(
                room.campus_code,
                campus_codes,
                "Campus",
                "campus_code",
                f"Phòng {room.room_code} tham chiếu cơ sở",
            )
        for capability in bundle.lecturer_capabilities:
            self._require_reference(
                capability.lecturer_code,
                lecturer_codes,
                "Lecturer",
                "lecturer_code",
                "Năng lực giảng dạy tham chiếu giảng viên",
            )
            self._require_reference(
                capability.course_code,
                course_codes,
                "Course",
                "course_code",
                "Năng lực giảng dạy tham chiếu môn học",
            )
        for item in bundle.room_equipment:
            self._require_reference(
                item.room_code,
                room_codes,
                "TeachingLocation",
                "location_code",
                "Thiết bị phòng tham chiếu phòng",
            )
            self._require_reference(
                item.equipment_code,
                equipment_codes,
                "Equipment",
                "equipment_code",
                "Thiết bị phòng tham chiếu thiết bị",
            )
        for section in bundle.course_sections:
            self._require_reference(
                section.course_code,
                course_codes,
                "Course",
                "course_code",
                f"Lớp {section.section_code} tham chiếu môn học",
            )
        for structure in bundle.course_teaching_structures:
            self._require_reference(
                structure.course_code,
                course_codes,
                "Course",
                "course_code",
                "Cấu trúc môn học tham chiếu môn",
            )
        for item in bundle.course_structure_equipment:
            self._require_structure_reference(item, structure_keys)
            self._require_reference(
                item.equipment_code,
                equipment_codes,
                "Equipment",
                "equipment_code",
                "Thiết bị phần giảng dạy tham chiếu thiết bị",
            )
        for availability in bundle.lecturer_availability:
            self._require_reference(
                availability.lecturer_code,
                lecturer_codes,
                "Lecturer",
                "lecturer_code",
                "Lịch giảng viên tham chiếu giảng viên",
            )
        for availability in bundle.room_availability:
            self._require_reference(
                availability.room_code,
                room_codes,
                "TeachingLocation",
                "location_code",
                "Lịch phòng tham chiếu phòng",
            )

    def apply(self, bundle: SemesterInputBundle) -> SemesterInputResult:
        cursor = self._connection.cursor()
        try:
            self.validate(bundle)
            self._ensure_term_is_mutable(bundle)
            self._upsert_term_calendar(bundle)
            self._upsert_simple_entities(bundle)
            self._upsert_course_teaching_structures(bundle)
            self._upsert_rooms(bundle)
            self._upsert_online_locations(bundle)
            self._upsert_sections(bundle)
            self._upsert_relation_entities(bundle)
            generation = TeachingPartGenerator().generate(
                cursor,
                term_code=bundle.term.term_code,
                number_of_weeks=bundle.term.number_of_weeks,
            )
            self._connection.commit()
        except ValueError:
            self._connection.rollback()
            raise
        except Exception as error:
            self._connection.rollback()
            raise SemesterInputPersistenceError(
                "Không thể lưu gói dữ liệu. Hãy kiểm tra các mã tham chiếu và dữ liệu đã tồn tại."
            ) from error
        counts = _bundle_counts(bundle)
        counts["generated_teaching_parts"] = generation.generated_part_count
        return SemesterInputResult(
            term_code=bundle.term.term_code,
            entity_counts=counts,
        )

    def _require_structure_reference(
        self,
        item: CourseTeachingStructureEquipmentInput,
        structures_in_bundle: set[tuple[str, str]],
    ) -> None:
        key = (item.course_code.upper(), item.part_type)
        if key in structures_in_bundle:
            return
        row = fetch_one_dict(self._connection.cursor().execute(
            """
            SELECT TOP 1 course_structure_id
            FROM CourseTeachingStructure
            WHERE course_code=? AND part_type=?
            """,
            item.course_code,
            item.part_type,
        ))
        if row is None:
            raise ValueError(
                "Thiết bị cấu trúc tham chiếu cấu trúc môn không tồn tại: "
                f"{item.course_code}/{item.part_type}."
            )

    def _require_reference(
        self,
        value: str,
        values_in_bundle: set[str],
        table: str,
        column: str,
        label: str,
    ) -> None:
        if value.upper() in values_in_bundle:
            return
        # table và column chỉ đến từ các lời gọi cố định phía trên, không nhận
        # trực tiếp từ request. Giá trị vẫn luôn truyền bằng parameter SQL.
        row = fetch_one_dict(self._connection.cursor().execute(
            f"SELECT TOP 1 {column} FROM {table} WHERE {column} = ?",
            value,
        ))
        if row is None:
            raise ValueError(f"{label} không tồn tại: {value}.")

    def _ensure_term_is_mutable(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        locked = fetch_one_dict(cursor.execute(
            """
            SELECT TOP 1 scenario_id
            FROM PlanningScenario
            WHERE term_code = ? AND status = 'LOCKED'
            """,
            bundle.term.term_code,
        ))
        if locked is not None:
            raise ValueError(
                "Học kỳ đã có scenario LOCKED; không được sửa dữ liệu nguồn của run tái lập."
            )
        existing = fetch_one_dict(cursor.execute(
            "SELECT start_date, end_date FROM AcademicTerm WHERE term_code = ?",
            bundle.term.term_code,
        ))
        if existing is not None and (
            existing["start_date"] != bundle.term.start_date
            or existing["end_date"] != bundle.term.end_date
        ):
            raise ValueError(
                "Không được đổi khoảng ngày của học kỳ đã tồn tại; hãy dùng mã học kỳ mới."
            )
        week_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT week_number,start_date,end_date
            FROM TermWeek WHERE term_code=? ORDER BY week_number
            """,
            bundle.term.term_code,
        ))
        for row in week_rows:
            week_number = int(row["week_number"])
            if not 1 <= week_number <= bundle.term.number_of_weeks:
                raise ValueError("TermWeek hiện có nằm ngoài số tuần của học kỳ.")
            expected_start = bundle.term.start_date + timedelta(
                days=(week_number - 1) * 7
            )
            if (
                row["start_date"] != expected_start
                or row["end_date"] != expected_start + timedelta(days=6)
            ):
                raise ValueError(
                    f"TermWeek {week_number} hiện có không khớp lịch tuần chuẩn."
                )

    def _upsert_term_calendar(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        term = bundle.term
        cursor.execute(
            """
            UPDATE AcademicTerm SET term_name = ?, status = ? WHERE term_code = ?;
            IF @@ROWCOUNT = 0
                INSERT INTO AcademicTerm(term_code, term_name, start_date, end_date, status)
                VALUES (?, ?, ?, ?, ?);
            """,
            term.term_name,
            term.status,
            term.term_code,
            term.term_code,
            term.term_name,
            term.start_date,
            term.end_date,
            term.status,
        )
        for week_number in range(1, term.number_of_weeks + 1):
            week_start = term.start_date + timedelta(days=(week_number - 1) * 7)
            week_end = week_start + timedelta(days=6)
            cursor.execute(
                """
                IF NOT EXISTS (SELECT 1 FROM TermWeek WHERE term_code = ? AND week_number = ?)
                    INSERT INTO TermWeek(term_code, week_number, start_date, end_date)
                    VALUES (?, ?, ?, ?);
                """,
                term.term_code,
                week_number,
                term.term_code,
                week_number,
                week_start,
                week_end,
            )
            for offset in range(7):
                calendar_date = week_start + timedelta(days=offset)
                cursor.execute(
                    """
                    IF NOT EXISTS (
                        SELECT 1 FROM TeachingDate WHERE term_code = ? AND calendar_date = ?
                    )
                        INSERT INTO TeachingDate(
                            term_code, calendar_date, week_number, iso_weekday, date_status
                        ) VALUES (?, ?, ?, ?, 'NORMAL');
                    """,
                    term.term_code,
                    calendar_date,
                    term.term_code,
                    calendar_date,
                    week_number,
                    calendar_date.isoweekday(),
                )

    def _upsert_simple_entities(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        for item in bundle.campuses:
            cursor.execute(
                """
                UPDATE Campus SET campus_name=?, address=?, is_active=? WHERE campus_code=?;
                IF @@ROWCOUNT=0 INSERT INTO Campus(campus_code,campus_name,address,is_active)
                VALUES(?,?,?,?);
                """,
                item.campus_name, item.address, item.is_active, item.campus_code,
                item.campus_code, item.campus_name, item.address, item.is_active,
            )
        for item in bundle.courses:
            cursor.execute(
                """
                UPDATE Course SET course_name=?, credits=?, is_active=? WHERE course_code=?;
                IF @@ROWCOUNT=0 INSERT INTO Course(course_code,course_name,credits,is_active)
                VALUES(?,?,?,?);
                """,
                item.course_name, item.credits, item.is_active, item.course_code,
                item.course_code, item.course_name, item.credits, item.is_active,
            )
        for item in bundle.lecturers:
            cursor.execute(
                """
                UPDATE Lecturer SET full_name=?,email=?,home_campus_code=?,
                    is_active=?,max_teaching_periods=? WHERE lecturer_code=?;
                IF @@ROWCOUNT=0 INSERT INTO Lecturer(
                    lecturer_code,full_name,email,home_campus_code,is_active,max_teaching_periods
                ) VALUES(?,?,?,?,?,?);
                """,
                item.full_name, item.email, item.home_campus_code, item.is_active,
                item.max_teaching_periods, item.lecturer_code,
                item.lecturer_code, item.full_name, item.email, item.home_campus_code,
                item.is_active, item.max_teaching_periods,
            )
        for item in bundle.equipment:
            cursor.execute(
                """
                UPDATE Equipment SET equipment_name=? WHERE equipment_code=?;
                IF @@ROWCOUNT=0 INSERT INTO Equipment(equipment_code,equipment_name) VALUES(?,?);
                """,
                item.equipment_name, item.equipment_code,
                item.equipment_code, item.equipment_name,
            )

    def _upsert_course_teaching_structures(
        self, bundle: SemesterInputBundle
    ) -> None:
        """Persist reusable teaching structure before term parts are generated."""

        cursor = self._connection.cursor()
        for item in bundle.course_teaching_structures:
            cursor.execute(
                """
                UPDATE CourseTeachingStructure
                SET total_periods=?,required_location_type=?,required_room_type=?,
                    max_sessions_per_week=?,allows_intensive=?,
                    max_candidate_plans=?,is_active=?,note=?
                WHERE course_code=? AND part_type=?;
                IF @@ROWCOUNT=0
                    INSERT INTO CourseTeachingStructure(
                        course_code,part_type,total_periods,
                        required_location_type,required_room_type,
                        max_sessions_per_week,allows_intensive,
                        max_candidate_plans,is_active,note
                    ) VALUES(?,?,?,?,?,?,?,?,?,?);
                """,
                item.total_periods, item.required_location_type,
                item.required_room_type, item.max_sessions_per_week,
                item.allows_intensive, item.max_candidate_plans,
                item.is_active, item.note, item.course_code, item.part_type,
                item.course_code, item.part_type, item.total_periods,
                item.required_location_type, item.required_room_type,
                item.max_sessions_per_week, item.allows_intensive,
                item.max_candidate_plans, item.is_active, item.note,
            )
        for item in bundle.course_structure_equipment:
            structure = fetch_one_dict(cursor.execute(
                """
                SELECT course_structure_id FROM CourseTeachingStructure
                WHERE course_code=? AND part_type=?
                """,
                item.course_code,
                item.part_type,
            ))
            if structure is None:
                raise ValueError(
                    "Không tồn tại cấu trúc môn "
                    f"{item.course_code}/{item.part_type}."
                )
            structure_id = int(structure["course_structure_id"])
            cursor.execute(
                """
                UPDATE CourseTeachingStructureRequiredEquipment
                SET minimum_quantity=?
                WHERE course_structure_id=? AND equipment_code=?;
                IF @@ROWCOUNT=0
                    INSERT INTO CourseTeachingStructureRequiredEquipment(
                        course_structure_id,equipment_code,minimum_quantity
                    ) VALUES(?,?,?);
                """,
                item.minimum_quantity, structure_id, item.equipment_code,
                structure_id, item.equipment_code, item.minimum_quantity,
            )

    def _upsert_rooms(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        for item in bundle.rooms:
            existing = fetch_one_dict(cursor.execute(
                "SELECT location_id, location_type FROM TeachingLocation WHERE location_code=?",
                item.room_code,
            ))
            if existing is not None and existing["location_type"] != "PHYSICAL_ROOM":
                raise ValueError(f"Địa điểm {item.room_code} đã tồn tại nhưng không phải phòng.")
            if existing is None:
                inserted = fetch_one_dict(cursor.execute(
                    """
                    INSERT INTO TeachingLocation(location_code,location_name,location_type,is_active)
                    OUTPUT INSERTED.location_id VALUES(?,?,'PHYSICAL_ROOM',?);
                    """,
                    item.room_code, item.room_name, item.is_active,
                ))
                if inserted is None:
                    raise RuntimeError("SQL Server không trả location_id vừa tạo.")
                location_id = int(inserted["location_id"])
            else:
                location_id = int(existing["location_id"])
                cursor.execute(
                    "UPDATE TeachingLocation SET location_name=?,is_active=? WHERE location_id=?",
                    item.room_name, item.is_active, location_id,
                )
            cursor.execute(
                """
                UPDATE Room SET campus_code=?,room_type=?,capacity=? WHERE location_id=?;
                IF @@ROWCOUNT=0 INSERT INTO Room(location_id,campus_code,room_type,capacity)
                VALUES(?,?,?,?);
                """,
                item.campus_code, item.room_type, item.capacity, location_id,
                location_id, item.campus_code, item.room_type, item.capacity,
            )

    def _upsert_online_locations(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        for item in bundle.online_locations:
            existing = fetch_one_dict(cursor.execute(
                "SELECT location_id, location_type FROM TeachingLocation WHERE location_code=?",
                item.location_code,
            ))
            if existing is not None and existing["location_type"] != "ONLINE":
                raise ValueError(
                    f"Địa điểm {item.location_code} đã tồn tại nhưng không phải lớp trực tuyến."
                )
            if existing is None:
                inserted = fetch_one_dict(cursor.execute(
                    """
                    INSERT INTO TeachingLocation(location_code,location_name,location_type,is_active)
                    OUTPUT INSERTED.location_id VALUES(?,?,'ONLINE',?);
                    """,
                    item.location_code, item.location_name, item.is_active,
                ))
                if inserted is None:
                    raise RuntimeError("SQL Server không trả location_id vừa tạo.")
                location_id = int(inserted["location_id"])
            else:
                location_id = int(existing["location_id"])
                cursor.execute(
                    "UPDATE TeachingLocation SET location_name=?,is_active=? WHERE location_id=?",
                    item.location_name, item.is_active, location_id,
                )
            cursor.execute(
                """
                UPDATE OnlineLocation SET platform_name=?,meeting_note=? WHERE location_id=?;
                IF @@ROWCOUNT=0 INSERT INTO OnlineLocation(location_id,platform_name,meeting_note)
                VALUES(?,?,?);
                """,
                item.platform_name, item.meeting_note, location_id,
                location_id, item.platform_name, item.meeting_note,
            )

    def _upsert_sections(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        term_code = bundle.term.term_code
        for item in bundle.course_sections:
            existing_section = fetch_one_dict(cursor.execute(
                "SELECT term_code FROM CourseSection WHERE section_code=?",
                item.section_code,
            ))
            if (
                existing_section is not None
                and str(existing_section["term_code"]) != term_code
            ):
                raise ValueError(
                    f"Mã lớp {item.section_code} đã thuộc học kỳ khác."
                )
            cursor.execute(
                """
                UPDATE CourseSection SET course_code=?,section_name=?,expected_enrollment=?,status=?
                WHERE section_code=? AND term_code=?;
                IF @@ROWCOUNT=0 INSERT INTO CourseSection(
                    section_code,term_code,course_code,section_name,expected_enrollment,status
                ) VALUES(?,?,?,?,?,?);
                """,
                item.course_code, item.section_name, item.expected_enrollment, item.status,
                item.section_code, term_code,
                item.section_code, term_code, item.course_code, item.section_name,
                item.expected_enrollment, item.status,
            )

    def _upsert_relation_entities(self, bundle: SemesterInputBundle) -> None:
        cursor = self._connection.cursor()
        term_code = bundle.term.term_code
        for item in bundle.lecturer_capabilities:
            cursor.execute(
                """
                UPDATE LecturerCourseCapability SET can_teach_lecture=?,can_teach_practice=?,
                    suitability_score=? WHERE lecturer_code=? AND course_code=?;
                IF @@ROWCOUNT=0 INSERT INTO LecturerCourseCapability(
                    lecturer_code,course_code,can_teach_lecture,can_teach_practice,suitability_score
                ) VALUES(?,?,?,?,?);
                """,
                item.can_teach_lecture, item.can_teach_practice, item.suitability_score,
                item.lecturer_code, item.course_code,
                item.lecturer_code, item.course_code, item.can_teach_lecture,
                item.can_teach_practice, item.suitability_score,
            )
        for item in bundle.room_equipment:
            room = _require_location_id(cursor, item.room_code)
            cursor.execute(
                """
                UPDATE RoomEquipment SET quantity=? WHERE room_location_id=? AND equipment_code=?;
                IF @@ROWCOUNT=0 INSERT INTO RoomEquipment(room_location_id,equipment_code,quantity)
                VALUES(?,?,?);
                """,
                item.quantity, room, item.equipment_code,
                room, item.equipment_code, item.quantity,
            )
        for item in bundle.lecturer_availability:
            cursor.execute(
                """
                IF NOT EXISTS (
                    SELECT 1 FROM LecturerAvailability
                    WHERE term_code=? AND lecturer_code=? AND scope_type=?
                      AND ISNULL(calendar_date,'19000101')=ISNULL(?,'19000101')
                      AND ISNULL(iso_weekday,0)=ISNULL(?,0)
                      AND start_period=? AND end_period=? AND availability_type=?
                ) INSERT INTO LecturerAvailability(
                    term_code,lecturer_code,scope_type,calendar_date,iso_weekday,
                    start_period,end_period,availability_type,preference_weight,note
                ) VALUES(?,?,?,?,?,?,?,?,?,?);
                """,
                term_code, item.lecturer_code, item.scope_type, item.calendar_date,
                item.iso_weekday, item.start_period, item.end_period,
                item.availability_type,
                term_code, item.lecturer_code, item.scope_type, item.calendar_date,
                item.iso_weekday, item.start_period, item.end_period,
                item.availability_type, item.preference_weight, item.note,
            )
        for item in bundle.room_availability:
            room = _require_location_id(cursor, item.room_code)
            cursor.execute(
                """
                IF NOT EXISTS (
                    SELECT 1 FROM RoomAvailability
                    WHERE term_code=? AND room_location_id=? AND scope_type=?
                      AND ISNULL(calendar_date,'19000101')=ISNULL(?,'19000101')
                      AND ISNULL(iso_weekday,0)=ISNULL(?,0)
                      AND start_period=? AND end_period=? AND availability_type=?
                ) INSERT INTO RoomAvailability(
                    term_code,room_location_id,scope_type,calendar_date,iso_weekday,
                    start_period,end_period,availability_type,note
                ) VALUES(?,?,?,?,?,?,?,?,?);
                """,
                term_code, room, item.scope_type, item.calendar_date,
                item.iso_weekday, item.start_period, item.end_period,
                item.availability_type,
                term_code, room, item.scope_type, item.calendar_date,
                item.iso_weekday, item.start_period, item.end_period,
                item.availability_type, item.note,
            )


def _require_location_id(cursor: Any, room_code: str) -> int:
    row = fetch_one_dict(cursor.execute(
        "SELECT location_id FROM TeachingLocation WHERE location_code=? AND location_type='PHYSICAL_ROOM'",
        room_code,
    ))
    if row is None:
        raise ValueError(f"Không tồn tại phòng {room_code}.")
    return int(row["location_id"])


def _bundle_counts(bundle: SemesterInputBundle) -> dict[str, int]:
    return {
        name: len(getattr(bundle, name))
        for name in (
            "campuses", "courses", "lecturers", "lecturer_capabilities",
            "rooms", "online_locations", "equipment", "room_equipment", "course_sections",
            "course_teaching_structures", "course_structure_equipment",
            "lecturer_availability", "room_availability",
        )
    }
