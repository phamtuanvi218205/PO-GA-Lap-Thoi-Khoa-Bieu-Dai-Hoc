import unittest
# FrozenInstanceError là lỗi được sinh ra khi cố sửa
# một dataclass có frozen=True.
from dataclasses import FrozenInstanceError

# import các class đã định nghĩa từ models.py

from src.gapo_timetabling.models import (
    AvailabilityType,
    AvailabilityWindow,
    ConstraintSetting,
    ConstraintType,
    Lecturer,
    ProblemInstance,
    Room,
    RoomType,
    SessionType,
    StudentGroup,
    TeachingEvent,
    TimeSlot,
)

# mỗi class kế thừa unittest case 
class TestModels(unittest.TestCase):
    # setUp được chạy lại trước MỖI test.
    # Nó chuẩn bị một bài toán thời khóa biểu rất nhỏ.
    def setUp(self)-> None:
        # tạo phòng lý thuyết đầu tiên
        self.lecture_room=Room(
            # chỉ số index phòng trong python
            room_index=0,
            # mã phòng thật trong db
            room_code="A301",
            # sức chứa
            capacity=80,
            # loại phòng gán là lý thuyết
            room_type=RoomType.LECTURE,
            # tên tòa nhà
            building_name="Tòa A",
            # tên cơ sở
            campus_name="140 Lê Trọng Tấn",
            # phòng đang hoạt động
            active=True
        )
        # Tạo một phòng máy.
        self.computer_lab = Room(
            # Đây là phòng thứ hai trong mảng nên index bằng 1.
            room_index=1,

            # Mã phòng trong database.
            room_code="A202",

            # Phòng máy chứa được 45 sinh viên.
            capacity=45,

            # Loại phòng là phòng máy.
            room_type=RoomType.COMPUTER_LAB,

            # Phòng thuộc tòa thực hành.
            building_name="Tòa A",

            # Phòng vẫn thuộc cơ sở chính.
            campus_name="140 Lê Trọng Tấn",

            # Phòng đang hoạt động.
            active=True,
        )
        # Tạo một giảng viên.
        self.lecturer = Lecturer(
            # Chỉ số giảng viên trong mảng Python.
            lecturer_index=0,

            # Mã giảng viên trong database.
            lecturer_code="GV01",
        )
        # Tạo một nhóm sinh viên.
        self.student_group = StudentGroup(
            # Chỉ số nhóm trong mảng Python.
            group_index=0,

            # Mã nhóm sinh viên trong database.
            group_code="CNTTK14",

            # Nhóm có 40 sinh viên.
            group_size=40,
        )
        # Tạo tiết 1 của sáng thứ 2.
        self.period_1 = TimeSlot(
            # Thứ 2 được lưu bằng số 2.
            day_of_week=2,

            # Đây là tiết đầu tiên.
            period_number=1,

            # Tiết này thuộc buổi sáng.
            session_type=SessionType.MORNING,

            # Đây là tiết được phép xếp lịch.
            teaching_slot=True,
        )
        # Tạo tiết 2 của sáng thứ 2.
        self.period_2 = TimeSlot(
            day_of_week=2,
            period_number=2,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )
        # Tạo tiết 3 của sáng thứ 2.
        self.period_3 = TimeSlot(
            day_of_week=2,
            period_number=3,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )
        # Tạo một buổi học cần được xếp.
        self.event = TeachingEvent(
            # Event này nằm ở cột 0 trong chromosome.
            event_index=0,

            # Đây là khóa chính của TeachingEvent trong database.
            event_id=1,

            # Event thuộc lớp học phần AI_01
            section_code="AI_01",

            # Đây là buổi thứ nhất của lớp học phần.
            event_number=1,

            # Giảng viên có lecturer_index bằng 0.
            lecturer_index=0,

            # Lớp có nhóm sinh viên group_index bằng 0.
            # Dấu phẩy trong (0,) rất quan trọng.
            # Nếu viết (0), Python sẽ hiểu đó là số nguyên.
            student_group_indices=(0,),

            # Event có 40 sinh viên.
            enrollment=40,

            # Event kéo dài liên tục 3 tiết.
            duration_periods=3,

            # Event yêu cầu phòng lý thuyết.
            required_room_type=RoomType.LECTURE,
        )
        # Tạo một khoảng thời gian được giảng viên ưu tiên.
        self.lecturer_preference = AvailabilityWindow(
            # lecturer_index của GV01 bằng 0.
            resource_index=0,

            # Giảng viên ưu tiên thứ 3.
            day_of_week=3,

            # Bắt đầu ưu tiên từ tiết 1.
            start_period=1,

            # Kết thúc ở tiết 5.
            end_period=5,

            # Đây là sở thích, không phải thời gian cấm.
            availability_type=AvailabilityType.PREFERRED,

            # Trọng số sở thích là 8.
            preference_weight=8,
        )
        # Tạo cấu hình ràng buộc sức chứa phòng.
        self.capacity_constraint = ConstraintSetting(
            # Mã phải giống mã cấu hình trong database.
            constraint_code="H05_ROOM_CAPACITY",

            # Đây là ràng buộc cứng.
            constraint_type=ConstraintType.HARD,

            # Vi phạm ràng buộc cứng bị phạt rất lớn.
            weight=1_000_000.0,

            # Ràng buộc đang được sử dụng.
            enabled=True,
        )
        # Gộp toàn bộ dữ liệu thành một bài toán hoàn chỉnh.
        self.problem = ProblemInstance(
            # Mã học kỳ đang được xếp.
            term_code="2026_HK1",

            # Bài toán có hai phòng.
            rooms=(
                self.lecture_room,
                self.computer_lab,
            ),

            # Tuple một giảng viên phải viết (self.lecturer,).
            lecturers=(self.lecturer,),

            # Tuple một nhóm sinh viên.
            student_groups=(self.student_group,),

            # Ba tiết học liên tục.
            time_slots=(
                self.period_1,
                self.period_2,
                self.period_3,
            ),

            # Bài toán hiện chỉ có một teaching event.
            events=(self.event,),

            # Một khoảng thời gian ưu tiên của giảng viên.
            lecturer_availabilities=(
                self.lecturer_preference,
            ),

            # Chưa có lịch bận hoặc ưu tiên của phòng.
            room_availabilities=(),

            # Bài toán có một cấu hình ràng buộc.
            constraint_settings=(
                self.capacity_constraint,
            ),
        )
        # Kiểm tra số chiều chromosome.
    def test_dimension_equals_event_count(self) -> None:

        # Có một TeachingEvent nên chromosome phải có một gene.
        self.assertEqual(self.problem.dimension, 1)

    # Kiểm tra số phòng.
    def test_room_count(self) -> None:

        # ProblemInstance đang chứa hai phòng.
        self.assertEqual(self.problem.room_count, 2)

    # Kiểm tra quan hệ giữa event và các index.
    def test_event_indices(self) -> None:

        # Event đầu tiên phải có event_index bằng 0.
        self.assertEqual(self.event.event_index, 0)

        # Event sử dụng giảng viên có index bằng 0.
        self.assertEqual(self.event.lecturer_index, 0)

        # Event thuộc đúng một nhóm sinh viên.
        self.assertEqual(
            self.event.student_group_indices,
            (0,),
        )

        # Event cần phòng lý thuyết.
        self.assertEqual(
            self.event.required_room_type,
            RoomType.LECTURE,
        )

    # Kiểm tra frozen=True.
    def test_room_is_immutable(self) -> None:

        # Việc thay đổi capacity phải phát sinh FrozenInstanceError.
        with self.assertRaises(FrozenInstanceError):
            self.lecture_room.capacity = 100

    # Kiểm tra dữ liệu Enum khớp với chuỗi trong JSON/database.
    def test_enum_values(self) -> None:

        # Giá trị thật của Enum phải là chuỗi LECTURE.
        self.assertEqual(
            RoomType.LECTURE.value,
            "LECTURE",
        )

        # Giá trị của loại availability phải là PREFERRED.
        self.assertEqual(
            AvailabilityType.PREFERRED.value,
            "PREFERRED",
        )


# Khối này chỉ chạy khi gọi trực tiếp file test_models.py.
if __name__ == "__main__":

    # Chạy tất cả hàm bắt đầu bằng test_ trong class TestModels.
    unittest.main()