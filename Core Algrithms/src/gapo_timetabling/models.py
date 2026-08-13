from dataclasses import dataclass
from enum import Enum

#enum

class RoomType(str,Enum):
    #các loại phòng học
    LECTURE = "LECTURE"
    COMPUTER_LAB = "COMPUTER_LAB"

class SessionType(str,Enum):
    #các buổi học trong 1 ngày
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"

class AvailabilityType(str,Enum):
    #mức độ khả dụng của giáo viên hoặc là phòng học
    UNAVAILABLE = "UNAVAILABLE"
    DISCOURAGED = "DISCOURAGED"
    PREFERRED = "PREFERRED"

class ConstraintType(str,Enum):
    #các loại ràng buộc
    HARD = "HARD"
    SOFT = "SOFT"

# data

@dataclass(frozen=True,slots=True)
class Room:
    #các phòng học
    room_index: int
    room_code: str
    capacity: int
    room_type: RoomType
    building_name: str
    campus_name: str
    active: bool

@dataclass(frozen=True,slots=True)
class Lecturer:
    #các giảng viên
    lecturer_index: int
    lecturer_code: str

@dataclass(frozen=True, slots=True)
class StudentGroup:
    #Nhóm sinh viên dùng để phát hiện trùng lịch

    group_index: int
    group_code: str
    group_size: int

@dataclass(frozen=True, slots=True)
class TimeSlot:
    #1 tiết học trong thời khóa biểu
    day_of_week: int
    period_number: int
    session_type: SessionType
    teaching_slot: bool

# teaching

@dataclass(frozen=True, slots=True)
class TeachingEvent:
    # một buổi học cần được vếp vào tkb
    # mỗi buổi học tương ứng với 1 gene trong chromosome
    event_index: int
    event_id: int
    section_code: str
    event_number: int
    lecturer_index: int
    student_group_indices: tuple[int, ...]
    enrollment: int
    duration_periods: int
    required_room_type: RoomType

# availability and constraints
@dataclass(frozen=True, slots=True)
class AvailabilityWindow:
    #Một khoảng thời gian bận, không ưu tiên hoặc được ưu tiên
    #resource_index có thể là lecturer_index hoặc room_index, tùy danh sách chứa đối tượng này
    resource_index: int
    day_of_week: int
    start_period: int
    end_period: int
    availability_type: AvailabilityType
    preference_weight: int

@dataclass(frozen=True, slots=True)
class ConstraintSetting:
    # trọng số của 1 ràng buộc
    constraint_code: str
    constraint_type: ConstraintType
    weight: float
    enabled: bool

# encoding and decoding

@dataclass(frozen=True, slots=True)
class CandidateOption:
    # 1 phương án hợp lệ riêng cho 1 teaching event
    # encoder có thể tạo nhiều candidate option cho mỗi event
    event_index: int
    room_index: int
    day_of_week: int
    start_period: int
    end_period: int
    session_type: SessionType

@dataclass(frozen=True, slots=True)
class Assignment:
    # kết quả sau khi giải mã 1 gene
    # dạng có thể trả về java hoặc lưu vào TimetableEntry
    event_id: int
    section_code: str
    event_number: int
    room_code: str
    day_of_week: int
    start_period: int
    end_period: int

# optimization input
@dataclass(frozen=True, slots=True)
class ProblemInstance:
    # toàn bộ dữ liệu đầu vào của 1 lần sắp xếp tkb
    term_code: str

    rooms: tuple[Room, ...]
    lecturers: tuple[Lecturer, ...]
    student_groups: tuple[StudentGroup, ...]
    time_slots: tuple[TimeSlot, ...]
    events: tuple[TeachingEvent, ...]

    lecturer_availabilities: tuple[AvailabilityWindow, ...]
    room_availabilities: tuple[AvailabilityWindow, ...]
    constraint_settings: tuple[ConstraintSetting, ...]
    @property
    def dimension(self) -> int:
        # số chiều chromosome bằng số teaching event
        return len(self.events)
    @property
    def room_count(self) -> int:
        # tổng số phòng
        return len(self.rooms)