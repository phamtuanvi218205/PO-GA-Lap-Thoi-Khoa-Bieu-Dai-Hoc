"""Kiểm thử các hàm mã hóa dữ liệu thời khóa biểu."""

import unittest
from dataclasses import replace

from gapo_timetabling.encoder import (
    get_consecutive_time_slots,
    is_resource_unavailable,
    period_ranges_overlap,
    room_can_host_event,
)
from gapo_timetabling.models import (
    AvailabilityType,
    AvailabilityWindow,
    Room,
    RoomType,
    SessionType,
    TeachingEvent,
    TimeSlot,
)


class TestRoomCanHostEvent(unittest.TestCase):
    """Kiểm thử riêng hàm room_can_host_event()."""

    def setUp(self) -> None:
        """Tạo dữ liệu mẫu mới trước khi chạy mỗi test."""

        # Phòng mẫu đang hoạt động, có 60 chỗ và là phòng lý thuyết.
        self.lecture_room = Room(
            room_index=0,
            room_code="A101",
            capacity=60,
            room_type=RoomType.LECTURE,
            building_name="A",
            campus_name="Main Campus",
            active=True,
        )

        # Sự kiện mẫu có 50 sinh viên và yêu cầu phòng lý thuyết.
        self.event = TeachingEvent(
            event_index=0,
            event_id=1,
            section_code="IT001-01",
            event_number=1,
            lecturer_index=0,
            student_group_indices=(0,),
            enrollment=50,
            duration_periods=2,
            required_room_type=RoomType.LECTURE,
        )

    def test_valid_room_can_host_event(self) -> None:
        """Phòng hoạt động, đủ chỗ và đúng loại phải được chấp nhận."""

        result = room_can_host_event(
            room=self.lecture_room,
            event=self.event,
        )

        self.assertTrue(result)

    def test_inactive_room_cannot_host_event(self) -> None:
        """Phòng không hoạt động phải bị loại."""

        inactive_room = replace(self.lecture_room, active=False)

        result = room_can_host_event(
            room=inactive_room,
            event=self.event,
        )

        self.assertFalse(result)

    def test_room_with_insufficient_capacity_is_rejected(self) -> None:
        """Phòng thiếu dù chỉ một chỗ cũng phải bị loại."""

        small_room = replace(
            self.lecture_room,
            capacity=self.event.enrollment - 1,
        )

        result = room_can_host_event(
            room=small_room,
            event=self.event,
        )

        self.assertFalse(result)

    def test_room_with_exact_capacity_is_accepted(self) -> None:
        """Phòng có sức chứa bằng số sinh viên phải được chấp nhận."""

        exact_room = replace(
            self.lecture_room,
            capacity=self.event.enrollment,
        )

        result = room_can_host_event(
            room=exact_room,
            event=self.event,
        )

        self.assertTrue(result)

    def test_wrong_room_type_is_rejected(self) -> None:
        """Phòng đủ chỗ nhưng sai loại phải bị loại."""

        computer_lab = replace(
            self.lecture_room,
            room_type=RoomType.COMPUTER_LAB,
        )

        result = room_can_host_event(
            room=computer_lab,
            event=self.event,
        )

        self.assertFalse(result)


class TestGetConsecutiveTimeSlots(unittest.TestCase):
    """Kiểm thử riêng hàm get_consecutive_time_slots()."""

    def setUp(self) -> None:
        """Tạo ba tiết liên tiếp trong buổi sáng của thứ Hai."""

        self.monday_period_1 = TimeSlot(
            day_of_week=2,
            period_number=1,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )
        self.monday_period_2 = TimeSlot(
            day_of_week=2,
            period_number=2,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )
        self.monday_period_3 = TimeSlot(
            day_of_week=2,
            period_number=3,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )

        self.time_slots = (
            self.monday_period_1,
            self.monday_period_2,
            self.monday_period_3,
        )

    def test_returns_consecutive_slots_when_valid(self) -> None:
        """Có đủ tiết 1, 2, 3 thì trả về đúng cả ba tiết."""

        result = get_consecutive_time_slots(
            time_slots=self.time_slots,
            day_of_week=2,
            start_period=1,
            duration_periods=3,
        )

        expected = (
            self.monday_period_1,
            self.monday_period_2,
            self.monday_period_3,
        )

        self.assertEqual(result, expected)

    def test_returns_none_when_a_period_is_missing(self) -> None:
        """Thiếu tiết 2 làm dãy tiết 1, 2, 3 không hợp lệ."""

        time_slots_without_period_2 = (
            self.monday_period_1,
            self.monday_period_3,
        )

        result = get_consecutive_time_slots(
            time_slots=time_slots_without_period_2,
            day_of_week=2,
            start_period=1,
            duration_periods=3,
        )

        self.assertIsNone(result)

    def test_returns_none_when_slot_is_not_for_teaching(self) -> None:
        """Một tiết teaching_slot=False làm cả dãy không hợp lệ."""

        blocked_period_2 = replace(
            self.monday_period_2,
            teaching_slot=False,
        )
        time_slots_with_blocked_period = (
            self.monday_period_1,
            blocked_period_2,
            self.monday_period_3,
        )

        result = get_consecutive_time_slots(
            time_slots=time_slots_with_blocked_period,
            day_of_week=2,
            start_period=1,
            duration_periods=3,
        )

        self.assertIsNone(result)

    def test_returns_none_when_slots_cross_sessions(self) -> None:
        """Tiết 5 buổi sáng không được nối với tiết 6 buổi chiều."""

        morning_period_5 = TimeSlot(
            day_of_week=2,
            period_number=5,
            session_type=SessionType.MORNING,
            teaching_slot=True,
        )
        afternoon_period_6 = TimeSlot(
            day_of_week=2,
            period_number=6,
            session_type=SessionType.AFTERNOON,
            teaching_slot=True,
        )

        result = get_consecutive_time_slots(
            time_slots=(morning_period_5, afternoon_period_6),
            day_of_week=2,
            start_period=5,
            duration_periods=2,
        )

        self.assertIsNone(result)

    def test_returns_none_when_starting_slot_does_not_exist(self) -> None:
        """Tiết bắt đầu không tồn tại thì không thể tạo dãy tiết."""

        result = get_consecutive_time_slots(
            time_slots=self.time_slots,
            day_of_week=2,
            start_period=5,
            duration_periods=2,
        )

        self.assertIsNone(result)

    def test_raises_error_when_duration_is_zero(self) -> None:
        """Thời lượng bằng 0 là dữ liệu sai và phải phát sinh lỗi."""

        with self.assertRaises(ValueError):
            get_consecutive_time_slots(
                time_slots=self.time_slots,
                day_of_week=2,
                start_period=1,
                duration_periods=0,
            )





class TestPeriodRangesOverlap(unittest.TestCase):
    """Kiểm thử riêng hàm period_ranges_overlap()."""

    def test_returns_true_when_ranges_partially_overlap(self) -> None:
        """Khoảng 2–5 và 4–7 giao nhau tại tiết 4–5."""

        result = period_ranges_overlap(
            first_start_period=2,
            first_end_period=5,
            second_start_period=4,
            second_end_period=7,
        )

        self.assertTrue(result)

    def test_returns_true_when_ranges_touch_at_one_period(self) -> None:
        """Khoảng 2–4 và 4–6 giao nhau tại tiết 4."""

        result = period_ranges_overlap(
            first_start_period=2,
            first_end_period=4,
            second_start_period=4,
            second_end_period=6,
        )

        self.assertTrue(result)

    def test_returns_false_when_ranges_do_not_overlap(self) -> None:
        """Khoảng 1–3 và 4–6 không có tiết chung."""

        result = period_ranges_overlap(
            first_start_period=1,
            first_end_period=3,
            second_start_period=4,
            second_end_period=6,
        )

        self.assertFalse(result)

    def test_raises_error_when_first_range_is_invalid(self) -> None:
        """Khoảng thứ nhất có start lớn hơn end phải phát sinh lỗi."""

        with self.assertRaises(ValueError):
            period_ranges_overlap(
                first_start_period=5,
                first_end_period=3,
                second_start_period=1,
                second_end_period=2,
            )

    def test_raises_error_when_second_range_is_invalid(self) -> None:
        """Khoảng thứ hai có start lớn hơn end phải phát sinh lỗi."""

        with self.assertRaises(ValueError):
            period_ranges_overlap(
                first_start_period=1,
                first_end_period=2,
                second_start_period=6,
                second_end_period=4,
            )


class TestIsResourceUnavailable(unittest.TestCase):
    """Kiểm thử riêng hàm is_resource_unavailable()."""

    def setUp(self) -> None:
        """Resource 0 bị UNAVAILABLE vào thứ Hai, tiết 2–4."""

        self.unavailable_window = AvailabilityWindow(
            resource_index=0,
            day_of_week=2,
            start_period=2,
            end_period=4,
            availability_type=AvailabilityType.UNAVAILABLE,
            preference_weight=100,
        )

    def test_returns_true_when_unavailable_window_overlaps(self) -> None:
        """Phương án tiết 3–5 giao với UNAVAILABLE tiết 2–4."""

        result = is_resource_unavailable(
            availability_windows=(self.unavailable_window,),
            resource_index=0,
            day_of_week=2,
            start_period=3,
            end_period=5,
        )

        self.assertTrue(result)

    def test_returns_false_for_different_resource(self) -> None:
        """Window của resource 0 không được chặn resource 1."""

        result = is_resource_unavailable(
            availability_windows=(self.unavailable_window,),
            resource_index=1,
            day_of_week=2,
            start_period=3,
            end_period=5,
        )

        self.assertIs(result, False)

    def test_returns_false_for_different_day(self) -> None:
        """Window thứ Hai không được chặn phương án thứ Ba."""

        result = is_resource_unavailable(
            availability_windows=(self.unavailable_window,),
            resource_index=0,
            day_of_week=3,
            start_period=3,
            end_period=5,
        )

        self.assertIs(result, False)

    def test_returns_false_when_periods_do_not_overlap(self) -> None:
        """UNAVAILABLE tiết 2–4 không chặn phương án tiết 5–7."""

        result = is_resource_unavailable(
            availability_windows=(self.unavailable_window,),
            resource_index=0,
            day_of_week=2,
            start_period=5,
            end_period=7,
        )

        self.assertIs(result, False)

    def test_preferred_window_does_not_block_resource(self) -> None:
        """PREFERRED là ràng buộc mềm nên không bị encoder loại."""

        preferred_window = replace(
            self.unavailable_window,
            availability_type=AvailabilityType.PREFERRED,
        )

        result = is_resource_unavailable(
            availability_windows=(preferred_window,),
            resource_index=0,
            day_of_week=2,
            start_period=3,
            end_period=5,
        )

        self.assertIs(result, False)

    def test_checks_later_windows_after_non_overlapping_window(self) -> None:
        """Window đầu không giao nhau nhưng window sau vẫn phải được kiểm tra."""

        non_overlapping_window = replace(
            self.unavailable_window,
            start_period=1,
            end_period=1,
        )
        later_overlapping_window = replace(
            self.unavailable_window,
            start_period=4,
            end_period=6,
        )

        result = is_resource_unavailable(
            availability_windows=(
                non_overlapping_window,
                later_overlapping_window,
            ),
            resource_index=0,
            day_of_week=2,
            start_period=4,
            end_period=5,
        )

        self.assertTrue(result)

    def test_raises_error_when_checked_range_is_invalid(self) -> None:
        """Khoảng cần kiểm tra có start lớn hơn end phải phát sinh lỗi."""

        with self.assertRaises(ValueError):
            is_resource_unavailable(
                availability_windows=(self.unavailable_window,),
                resource_index=0,
                day_of_week=2,
                start_period=6,
                end_period=4,
            )


if __name__ == "__main__":
    unittest.main()
