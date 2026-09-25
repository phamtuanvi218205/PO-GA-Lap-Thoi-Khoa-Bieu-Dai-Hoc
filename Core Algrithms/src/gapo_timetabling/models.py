"""Các model bất biến dùng làm hợp đồng dữ liệu cho core GA–PO.

Module này chỉ mô tả dữ liệu đầu vào và đầu ra của thuật toán. Nó không truy
vấn database và không chứa logic của GA, PO, decoder, repair hoặc fitness.
"""

from dataclasses import dataclass
from datetime import date, time
from enum import Enum


# ---------------------------------------------------------------------------
# Enum phải khớp với chuỗi được lưu trong SQL Server và Java.
# ---------------------------------------------------------------------------

class AcademicTermStatus(str, Enum):
    """Vòng đời nghiệp vụ của một học kỳ trong hệ thống lập lịch."""

    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DateStatus(str, Enum):
    """Khả năng sử dụng của một ngày thuộc lịch giảng dạy."""

    NORMAL = "NORMAL"
    HOLIDAY = "HOLIDAY"
    MAKEUP_ALLOWED = "MAKEUP_ALLOWED"


class SessionType(str, Enum):
    """Ca học dùng để ngăn một khung tiết đi xuyên qua ranh giới ca."""

    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"


class PartType(str, Enum):
    """Loại nội dung của một phần giảng dạy trong lớp học phần."""

    LECTURE = "LECTURE"
    PRACTICE = "PRACTICE"


class LocationType(str, Enum):
    """Nhóm địa điểm mà một buổi học có thể sử dụng."""

    PHYSICAL_ROOM = "PHYSICAL_ROOM"
    ONLINE = "ONLINE"


class RoomType(str, Enum):
    """Phân loại phòng vật lý theo mục đích giảng dạy."""

    LECTURE_ROOM = "LECTURE_ROOM"
    COMPUTER_LAB = "COMPUTER_LAB"


class AvailabilityScopeType(str, Enum):
    """Phạm vi áp dụng của một cửa sổ khả dụng theo ngày hoặc theo thứ."""

    DATE = "DATE"
    WEEKDAY = "WEEKDAY"


class AvailabilityType(str, Enum):
    """Mức khả dụng của giảng viên hoặc địa điểm tại một khoảng thời gian."""

    UNAVAILABLE = "UNAVAILABLE"
    DISCOURAGED = "DISCOURAGED"
    PREFERRED = "PREFERRED"


class ConstraintType(str, Enum):
    """Phân biệt điều kiện bắt buộc và tiêu chí chất lượng có thể đánh đổi."""

    HARD = "HARD"
    SOFT = "SOFT"


class TeachingPlanStatus(str, Enum):
    """Trạng thái phê duyệt của phương án chia một phần học thành các buổi."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ScenarioScopeType(str, Enum):
    """Phạm vi dữ liệu được đưa vào một lần lập lịch."""

    FULL_TERM = "FULL_TERM"
    SUBSET = "SUBSET"


class PlanningScenarioStatus(str, Enum):
    """Vòng đời của bộ đề bài trước khi tạo snapshot tối ưu."""

    DRAFT = "DRAFT"
    READY = "READY"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Lịch học kỳ và miền thời gian.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AcademicTerm:
    """Khoảng thời gian tổng thể mà lịch giảng dạy được xây dựng."""

    term_code: str
    term_name: str
    start_date: date
    end_date: date
    status: AcademicTermStatus

    def __post_init__(self) -> None:
        """Từ chối học kỳ có khoảng ngày đảo ngược."""

        if self.start_date > self.end_date:
            raise ValueError("Ngày bắt đầu học kỳ phải trước hoặc bằng ngày kết thúc.")


@dataclass(frozen=True, slots=True)
class TermWeek:
    """Một tuần đánh số theo nghiệp vụ bên trong học kỳ."""

    week_number: int
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        """Kiểm tra số tuần dương và khoảng ngày hợp lệ."""

        if self.week_number < 1:
            raise ValueError("Số tuần phải bắt đầu từ 1.")
        if self.start_date > self.end_date:
            raise ValueError("Ngày bắt đầu tuần phải trước hoặc bằng ngày kết thúc.")


@dataclass(frozen=True, slots=True)
class TeachingDate:
    """Một ngày cụ thể có thể xuất hiện trong phương án xếp lịch."""

    calendar_date: date
    week_number: int
    iso_weekday: int
    status: DateStatus

    def __post_init__(self) -> None:
        """Bảo đảm ngày, tuần và thứ ISO mô tả cùng một ngày lịch."""

        if self.week_number < 1:
            raise ValueError("Ngày giảng dạy phải thuộc một tuần hợp lệ.")
        if not 1 <= self.iso_weekday <= 7:
            raise ValueError("ISO weekday phải nằm trong khoảng 1..7.")
        if self.calendar_date.isoweekday() != self.iso_weekday:
            raise ValueError("iso_weekday không khớp với calendar_date.")


@dataclass(frozen=True, slots=True)
class TimePeriod:
    """Một tiết học có số thứ tự, giờ bắt đầu, giờ kết thúc và ca học."""

    period_number: int
    start_time: time
    end_time: time
    session_type: SessionType

    def __post_init__(self) -> None:
        """Kiểm tra miền số tiết và thứ tự thời gian trong tiết."""

        if not 1 <= self.period_number <= 16:
            raise ValueError("Tiết học phải nằm trong khoảng 1..16.")
        if self.start_time >= self.end_time:
            raise ValueError("Giờ bắt đầu tiết phải trước giờ kết thúc.")


@dataclass(frozen=True, slots=True)
class AllowedPeriodBlock:
    """Khung tiết liên tục được nhà trường cho phép dùng cho một buổi học."""

    start_period: int
    duration_periods: int

    def __post_init__(self) -> None:
        """Bảo đảm khung có độ dài dương và không vượt quá tiết 16."""

        if self.start_period < 1 or self.duration_periods < 1:
            raise ValueError("Khung tiết phải có vị trí và thời lượng dương.")
        if self.end_period > 16:
            raise ValueError("Khung tiết không được vượt quá tiết 16.")

    @property
    def end_period(self) -> int:
        """Trả về tiết cuối của khung, tính cả tiết bắt đầu."""

        return self.start_period + self.duration_periods - 1


@dataclass(frozen=True, slots=True)
class TeachingDurationRule:
    """Một thời lượng buổi được phép cho một loại phần giảng dạy."""

    part_type: PartType
    duration_periods: int
    is_standard: bool

    def __post_init__(self) -> None:
        """Giới hạn thời lượng buổi trong miền tiết mà core hỗ trợ."""

        if not 1 <= self.duration_periods <= 16:
            raise ValueError("Thời lượng được phép phải nằm trong khoảng 1..16.")


# ---------------------------------------------------------------------------
# Địa điểm giảng dạy.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CampusTravelTime:
    """Thời gian tối thiểu để di chuyển giữa hai cơ sở khác nhau."""

    from_campus_code: str
    to_campus_code: str
    travel_minutes: int

    def __post_init__(self) -> None:
        """Bảo đảm quan hệ di chuyển có ý nghĩa và thời gian không âm."""

        if self.from_campus_code == self.to_campus_code:
            raise ValueError("Thời gian di chuyển chỉ cần cho hai cơ sở khác nhau.")
        if self.travel_minutes < 0:
            raise ValueError("Thời gian di chuyển không được âm.")


@dataclass(frozen=True, slots=True)
class TeachingLocation:
    """Lớp cha chung để Room và OnlineLocation dùng cùng location_index."""

    location_index: int
    location_id: int
    location_code: str
    location_name: str
    active: bool

    def __post_init__(self) -> None:
        """Kiểm tra chỉ số nén dùng trong vector và miền option."""

        if self.location_index < 0:
            raise ValueError("location_index không được âm.")

    @property
    def location_type(self) -> LocationType:
        """Yêu cầu lớp con khai báo loại địa điểm cụ thể."""

        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Room(TeachingLocation):
    """Phòng vật lý cùng sức chứa và danh mục thiết bị hiện có."""

    campus_code: str
    room_type: RoomType
    capacity: int | None
    equipment_quantities: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        """Mở rộng kiểm tra chung bằng điều kiện sức chứa và thiết bị."""

        super(Room, self).__post_init__()
        if self.capacity is not None and self.capacity <= 0:
            raise ValueError("Sức chứa phòng phải dương hoặc None.")
        if any(quantity < 1 for _, quantity in self.equipment_quantities):
            raise ValueError("Số lượng thiết bị phải lớn hơn hoặc bằng 1.")

    @property
    def location_type(self) -> LocationType:
        """Đánh dấu đối tượng là một phòng vật lý."""

        return LocationType.PHYSICAL_ROOM


@dataclass(frozen=True, slots=True)
class OnlineLocation(TeachingLocation):
    """Không gian lớp học trực tuyến được quản lý như một địa điểm."""

    platform_name: str

    @property
    def location_type(self) -> LocationType:
        """Đánh dấu đối tượng là một địa điểm trực tuyến."""

        return LocationType.ONLINE


# ---------------------------------------------------------------------------
# Dữ liệu nghiệp vụ trước khi sinh viên đăng ký.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Lecturer:
    """Giảng viên đã được phân công trước khi thuật toán xếp lịch."""

    lecturer_index: int
    lecturer_code: str
    full_name: str
    home_campus_code: str | None = None

    def __post_init__(self) -> None:
        """Bảo đảm chỉ số giảng viên có thể dùng làm chỉ số mảng."""

        if self.lecturer_index < 0:
            raise ValueError("lecturer_index không được âm.")


@dataclass(frozen=True, slots=True)
class Course:
    """Môn học trong danh mục đào tạo."""

    course_code: str
    course_name: str


@dataclass(frozen=True, slots=True)
class CourseSection:
    """Lớp học phần mở trước đăng ký, kèm chỉ tiêu sinh viên dự kiến."""

    section_code: str
    course_code: str
    section_name: str
    expected_enrollment: int | None

    def __post_init__(self) -> None:
        """Cho phép thiếu chỉ tiêu nhưng không chấp nhận giá trị không dương."""

        if self.expected_enrollment is not None and self.expected_enrollment <= 0:
            raise ValueError("Chỉ tiêu dự kiến phải dương hoặc None.")


@dataclass(frozen=True, slots=True)
class TeachingPart:
    """Khối lượng lý thuyết hoặc thực hành phải hoàn thành cho một lớp.

    Giảng viên, tổng số tiết và yêu cầu địa điểm đã được xác định trước khi
    tối ưu. Một ``TeachingPart`` có thể có nhiều ``TeachingPlan`` thay thế.
    """

    teaching_part_index: int
    teaching_part_id: int
    part_code: str
    section_code: str
    part_type: PartType
    lecturer_index: int
    total_periods: int
    required_location_type: LocationType
    required_room_type: RoomType | None
    required_equipment: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        """Kiểm tra tính nhất quán giữa loại địa điểm, phòng và thiết bị."""

        if self.teaching_part_index < 0:
            raise ValueError("teaching_part_index không được âm.")
        if self.total_periods <= 0:
            raise ValueError("Tổng số tiết phải lớn hơn 0.")

        if self.required_location_type == LocationType.PHYSICAL_ROOM:
            if self.required_room_type is None:
                raise ValueError("Phần học tại trường phải khai báo loại phòng.")
        elif self.required_room_type is not None:
            raise ValueError("Phần học online không được yêu cầu loại phòng vật lý.")

        if any(quantity < 1 for _, quantity in self.required_equipment):
            raise ValueError("Số lượng thiết bị yêu cầu phải lớn hơn hoặc bằng 1.")


@dataclass(frozen=True, slots=True)
class TeachingPlan:
    """Phương án chia một ``TeachingPart`` thành các buổi cụ thể.

    Scenario chỉ được chọn một plan đã phê duyệt cho mỗi phần giảng dạy.
    Các ``ClassSession`` thuộc plan xác định tuần và thời lượng từng buổi.
    """

    teaching_plan_id: int
    plan_code: str
    teaching_part_index: int
    status: TeachingPlanStatus
    allows_intensive: bool


@dataclass(frozen=True, slots=True)
class ClassSession:
    """Một buổi nguyên tử cần được gán ngày, khung tiết và địa điểm.

    ``session_index`` là vị trí gene tương ứng trong vector nghiệm. Buổi đã
    biết tuần, thời lượng và plan nguồn nhưng chưa biết vị trí lịch cuối cùng.
    """

    session_index: int
    class_session_id: int
    teaching_plan_id: int
    session_number: int
    week_number: int
    duration_periods: int
    required_location_type: LocationType

    def __post_init__(self) -> None:
        """Kiểm tra chỉ số, số thứ tự, tuần và thời lượng của buổi."""

        if self.session_index < 0:
            raise ValueError("session_index không được âm.")
        if self.session_number < 1 or self.week_number < 1:
            raise ValueError("Số thứ tự buổi và số tuần phải bắt đầu từ 1.")
        if not 1 <= self.duration_periods <= 16:
            raise ValueError("Thời lượng buổi phải nằm trong khoảng 1..16.")


@dataclass(frozen=True, slots=True)
class PlanningScenarioItem:
    """Lựa chọn đúng một ``TeachingPlan`` cho một ``TeachingPart``."""

    teaching_part_index: int
    teaching_plan_id: int


@dataclass(frozen=True, slots=True)
class PlanningScenario:
    """Tập các plan được tối ưu chung trong một lần lập lịch.

    Scenario có thể bao phủ toàn học kỳ hoặc một tập con. Chỉ trạng thái
    ``LOCKED`` mới được phép tạo ``ProblemInstance`` để bảo đảm tái lập.
    """

    scenario_id: int
    scenario_code: str
    term_code: str
    scope_type: ScenarioScopeType
    status: PlanningScenarioStatus
    items: tuple[PlanningScenarioItem, ...]

    def __post_init__(self) -> None:
        """Ngăn một phần giảng dạy bị chọn đồng thời nhiều plan."""

        part_indices = [item.teaching_part_index for item in self.items]
        if len(part_indices) != len(set(part_indices)):
            raise ValueError("Scenario chỉ được chọn một plan cho mỗi TeachingPart.")


# ---------------------------------------------------------------------------
# Availability, cấu hình ràng buộc và dữ liệu trao đổi encoder/decoder.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AvailabilityWindow:
    """Cửa sổ cấm, không khuyến khích hoặc ưu tiên cho một tài nguyên.

    Phạm vi ``DATE`` áp dụng cho một ngày cụ thể; ``WEEKDAY`` lặp lại theo
    thứ trong tuần. Chỉ ``UNAVAILABLE`` là điều kiện cứng ở encoder.
    """

    resource_index: int
    scope_type: AvailabilityScopeType
    start_period: int
    end_period: int
    availability_type: AvailabilityType
    calendar_date: date | None = None
    iso_weekday: int | None = None
    preference_weight: float | None = None

    def __post_init__(self) -> None:
        """Kiểm tra phạm vi thời gian và dữ liệu đi kèm từng loại availability."""

        if self.resource_index < 0:
            raise ValueError("resource_index không được âm.")
        if not 1 <= self.start_period <= self.end_period <= 16:
            raise ValueError("Khoảng tiết availability không hợp lệ.")

        if self.scope_type == AvailabilityScopeType.DATE:
            if self.calendar_date is None or self.iso_weekday is not None:
                raise ValueError("Availability DATE phải có ngày và không có thứ lặp.")
        else:
            if self.calendar_date is not None or self.iso_weekday is None:
                raise ValueError("Availability WEEKDAY phải có thứ và không có ngày cụ thể.")
            if not 1 <= self.iso_weekday <= 7:
                raise ValueError("ISO weekday phải nằm trong khoảng 1..7.")

        if self.availability_type == AvailabilityType.UNAVAILABLE:
            if self.preference_weight is not None:
                raise ValueError("UNAVAILABLE không dùng trọng số preference.")
        elif self.preference_weight is not None and self.preference_weight < 0:
            raise ValueError("Trọng số preference không được âm.")


@dataclass(frozen=True, slots=True)
class ConstraintSetting:
    """Cấu hình bật/tắt, tầng ưu tiên và trọng số của một tiêu chí."""

    constraint_code: str
    constraint_type: ConstraintType
    priority_tier: int
    weight: float | None
    enabled: bool

    def __post_init__(self) -> None:
        """Giới hạn tầng ưu tiên và ngăn trọng số âm."""

        if not 1 <= self.priority_tier <= 3:
            raise ValueError("priority_tier phải nằm trong khoảng 1..3.")
        if self.weight is not None and self.weight < 0:
            raise ValueError("Trọng số không được âm.")


@dataclass(frozen=True, slots=True)
class SessionOption:
    """Một lựa chọn ngày, khung tiết và địa điểm cho một ``ClassSession``.

    Option chỉ hợp lệ ở cấp một buổi. Tính tương thích với các option khác
    được decoder và validator kiểm tra khi ghép thành lịch hoàn chỉnh.
    """

    session_index: int
    location_index: int
    teaching_date: date
    start_period: int
    end_period: int


@dataclass(frozen=True, slots=True)
class TimetableAssignment:
    """Bản ghi lịch đã giải mã để tầng Java lưu thành ``TimetableEntry``."""

    class_session_id: int
    section_code: str
    lecturer_code: str
    teaching_date: date
    location_code: str
    location_type: LocationType
    start_period: int
    end_period: int


# ---------------------------------------------------------------------------
# Snapshot bất biến của đúng một lần chạy thuật toán.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProblemInstance:
    """Snapshot bất biến chứa toàn bộ đề bài mà Python cần để tối ưu.

    Đối tượng gom scenario đã khóa, lịch học kỳ, tài nguyên, availability và
    các quy tắc liên quan. Việc kiểm tra chéo khi khởi tạo giúp mọi thuật toán
    nhận cùng một đầu vào nhất quán và có thể tái lập kết quả.
    """

    term: AcademicTerm
    scenario: PlanningScenario
    weeks: tuple[TermWeek, ...]
    teaching_dates: tuple[TeachingDate, ...]
    time_periods: tuple[TimePeriod, ...]
    allowed_period_blocks: tuple[AllowedPeriodBlock, ...]
    teaching_duration_rules: tuple[TeachingDurationRule, ...]
    locations: tuple[TeachingLocation, ...]
    lecturers: tuple[Lecturer, ...]
    courses: tuple[Course, ...]
    course_sections: tuple[CourseSection, ...]
    teaching_parts: tuple[TeachingPart, ...]
    teaching_plans: tuple[TeachingPlan, ...]
    class_sessions: tuple[ClassSession, ...]
    lecturer_availabilities: tuple[AvailabilityWindow, ...]
    room_availabilities: tuple[AvailabilityWindow, ...]
    campus_travel_times: tuple[CampusTravelTime, ...]
    constraint_settings: tuple[ConstraintSetting, ...]

    def __post_init__(self) -> None:
        """Chạy toàn bộ kiểm tra tính toàn vẹn của snapshot theo thứ tự."""

        self._validate_indices()
        self._validate_calendar()
        self._validate_duration_rules()
        self._validate_availability_windows()
        self._validate_scenario_and_sessions()

    def _validate_calendar(self) -> None:
        """Kiểm tra quan hệ giữa học kỳ, tuần học và ngày giảng dạy."""

        week_numbers = [week.week_number for week in self.weeks]
        if len(week_numbers) != len(set(week_numbers)):
            raise ValueError("Số tuần trong học kỳ không được trùng nhau.")

        weeks_by_number = {
            week.week_number: week
            for week in self.weeks
        }
        for week in self.weeks:
            if (
                week.start_date < self.term.start_date
                or week.end_date > self.term.end_date
            ):
                raise ValueError(
                    f"Tuần {week.week_number} nằm ngoài khoảng ngày của học kỳ."
                )

        calendar_dates = [item.calendar_date for item in self.teaching_dates]
        if len(calendar_dates) != len(set(calendar_dates)):
            raise ValueError("TeachingDate không được trùng ngày trong một học kỳ.")

        for teaching_date in self.teaching_dates:
            if not (
                self.term.start_date
                <= teaching_date.calendar_date
                <= self.term.end_date
            ):
                raise ValueError(
                    f"Ngày {teaching_date.calendar_date} nằm ngoài học kỳ."
                )

            week = weeks_by_number.get(teaching_date.week_number)
            if week is None:
                raise ValueError(
                    f"Ngày {teaching_date.calendar_date} tham chiếu tuần không tồn tại."
                )
            if not week.start_date <= teaching_date.calendar_date <= week.end_date:
                raise ValueError(
                    f"Ngày {teaching_date.calendar_date} không nằm trong tuần "
                    f"{teaching_date.week_number}."
                )

    def _validate_duration_rules(self) -> None:
        """Bảo đảm mỗi cặp loại phần–thời lượng chỉ xuất hiện một lần."""

        rule_keys = [
            (rule.part_type, rule.duration_periods)
            for rule in self.teaching_duration_rules
        ]
        if len(rule_keys) != len(set(rule_keys)):
            raise ValueError("Quy tắc thời lượng không được trùng loại phần và số tiết.")

    def _validate_availability_windows(self) -> None:
        """Áp dụng quy tắc riêng của availability giảng viên và phòng."""

        valid_lecturer_indices = {
            lecturer.lecturer_index
            for lecturer in self.lecturers
        }
        for window in self.lecturer_availabilities:
            if window.resource_index not in valid_lecturer_indices:
                raise ValueError("LecturerAvailability tham chiếu giảng viên không tồn tại.")
            if (
                window.availability_type != AvailabilityType.UNAVAILABLE
                and window.preference_weight is None
            ):
                raise ValueError(
                    "LecturerAvailability PREFERRED/DISCOURAGED phải có trọng số."
                )

        valid_room_indices = {
            room.location_index
            for room in self.rooms
        }
        for window in self.room_availabilities:
            if window.resource_index not in valid_room_indices:
                raise ValueError("RoomAvailability tham chiếu phòng không tồn tại.")
            if window.availability_type == AvailabilityType.PREFERRED:
                raise ValueError("RoomAvailability không hỗ trợ PREFERRED.")
            if window.preference_weight is not None:
                raise ValueError(
                    "RoomAvailability không lưu preference_weight trong schema hiện tại."
                )

    def _validate_indices(self) -> None:
        """Bảo đảm các chỉ số nén liên tục và đồng nhất với thứ tự tuple."""

        expected_session_indices = tuple(range(len(self.class_sessions)))
        actual_session_indices = tuple(session.session_index for session in self.class_sessions)
        if actual_session_indices != expected_session_indices:
            raise ValueError("session_index phải liên tục từ 0 và theo đúng thứ tự gene.")

        expected_location_indices = tuple(range(len(self.locations)))
        actual_location_indices = tuple(location.location_index for location in self.locations)
        if actual_location_indices != expected_location_indices:
            raise ValueError("location_index phải liên tục từ 0.")

        expected_lecturer_indices = tuple(range(len(self.lecturers)))
        actual_lecturer_indices = tuple(lecturer.lecturer_index for lecturer in self.lecturers)
        if actual_lecturer_indices != expected_lecturer_indices:
            raise ValueError("lecturer_index phải liên tục từ 0.")

        expected_part_indices = tuple(range(len(self.teaching_parts)))
        actual_part_indices = tuple(part.teaching_part_index for part in self.teaching_parts)
        if actual_part_indices != expected_part_indices:
            raise ValueError("teaching_part_index phải liên tục từ 0.")

    def _validate_scenario_and_sessions(self) -> None:
        """Kiểm tra chuỗi quan hệ scenario → plan → session → teaching part."""

        if self.scenario.term_code != self.term.term_code:
            raise ValueError("Scenario và ProblemInstance phải thuộc cùng học kỳ.")
        if self.scenario.status != PlanningScenarioStatus.LOCKED:
            raise ValueError("Chỉ scenario đã LOCKED mới được dùng để chạy thuật toán.")

        parts_by_index = {
            part.teaching_part_index: part
            for part in self.teaching_parts
        }
        plans_by_id = {
            plan.teaching_plan_id: plan
            for plan in self.teaching_plans
        }
        scenario_part_indices = {
            item.teaching_part_index
            for item in self.scenario.items
        }

        if scenario_part_indices != set(parts_by_index):
            raise ValueError("Scenario phải chọn đúng một plan cho mọi TeachingPart trong phạm vi.")

        selected_plan_ids: set[int] = set()
        for item in self.scenario.items:
            plan = plans_by_id.get(item.teaching_plan_id)
            if plan is None:
                raise ValueError("Scenario tham chiếu TeachingPlan không tồn tại.")
            if plan.teaching_part_index != item.teaching_part_index:
                raise ValueError("TeachingPlan được chọn không thuộc TeachingPart tương ứng.")
            if plan.status != TeachingPlanStatus.APPROVED:
                raise ValueError("Scenario chỉ được chọn TeachingPlan đã APPROVED.")
            selected_plan_ids.add(plan.teaching_plan_id)

        sessions_by_plan: dict[int, list[ClassSession]] = {
            plan_id: []
            for plan_id in selected_plan_ids
        }
        valid_weeks = {week.week_number for week in self.weeks}

        for session in self.class_sessions:
            if session.teaching_plan_id not in selected_plan_ids:
                raise ValueError("ClassSession phải thuộc plan được scenario chọn.")
            if session.week_number not in valid_weeks:
                raise ValueError("ClassSession tham chiếu tuần không tồn tại trong học kỳ.")
            sessions_by_plan[session.teaching_plan_id].append(session)

        for item in self.scenario.items:
            part = parts_by_index[item.teaching_part_index]
            sessions = sessions_by_plan[item.teaching_plan_id]
            planned_periods = sum(session.duration_periods for session in sessions)

            allowed_durations = {
                rule.duration_periods
                for rule in self.teaching_duration_rules
                if rule.part_type == part.part_type
            }
            if not allowed_durations:
                raise ValueError(
                    f"Chưa khai báo quy tắc thời lượng cho {part.part_type.value}."
                )

            invalid_durations = sorted({
                session.duration_periods
                for session in sessions
                if session.duration_periods not in allowed_durations
            })
            if invalid_durations:
                raise ValueError(
                    f"Part {part.part_code} có thời lượng buổi {invalid_durations} "
                    f"không được phép cho {part.part_type.value}."
                )

            if planned_periods != part.total_periods:
                raise ValueError(
                    f"Plan {item.teaching_plan_id} có {planned_periods} tiết, "
                    f"không bằng {part.total_periods} tiết của {part.part_code}."
                )

            if any(
                session.required_location_type != part.required_location_type
                for session in sessions
            ):
                raise ValueError("Loại địa điểm của ClassSession không khớp TeachingPart.")

    @property
    def dimension(self) -> int:
        """Số gene bằng đúng số ClassSession trong scenario đã khóa."""
        return len(self.class_sessions)

    @property
    def location_count(self) -> int:
        """Tổng số địa điểm vật lý và trực tuyến trong snapshot."""

        return len(self.locations)

    @property
    def rooms(self) -> tuple[Room, ...]:
        """Lọc các địa điểm vật lý, giữ nguyên thứ tự chỉ số ban đầu."""

        return tuple(location for location in self.locations if isinstance(location, Room))

    @property
    def online_locations(self) -> tuple[OnlineLocation, ...]:
        """Lọc các địa điểm trực tuyến, giữ nguyên thứ tự chỉ số ban đầu."""

        return tuple(
            location
            for location in self.locations
            if isinstance(location, OnlineLocation)
        )
