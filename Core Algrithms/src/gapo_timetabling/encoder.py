"""Các hàm chuẩn bị miền lựa chọn cho thuật toán GA-PO."""

from .models import (
    AvailabilityType,
    AvailabilityWindow,
    CandidateOption,
    ProblemInstance,
    Room,
    TeachingEvent,
    TimeSlot,
)


def room_can_host_event(room: Room, event: TeachingEvent) -> bool:
    """
    Kiểm tra một phòng học có phù hợp với một sự kiện hay không.

    Hàm kiểm tra ba điều kiện riêng của phòng:
    - Phòng đang hoạt động.
    - Phòng đủ sức chứa cho toàn bộ sinh viên.
    - Phòng đúng loại mà sự kiện yêu cầu.

    Hàm chưa kiểm tra xung đột lịch hoặc khoảng thời gian UNAVAILABLE.
    """

    # Phòng đã ngừng hoạt động thì không được đưa vào miền lựa chọn.
    if not room.active:
        return False

    # enrollment là số sinh viên tham gia sự kiện.
    if room.capacity < event.enrollment:
        return False

    # required_room_type trong TeachingEvent hiện là bắt buộc.
    if room.room_type != event.required_room_type:
        return False

    # Phòng đã vượt qua cả ba điều kiện.
    return True
def get_consecutive_time_slots(
        time_slots:tuple[TimeSlot,...],
        day_of_week:int,
        start_period:int,
        duration_periods:int,
)->tuple[TimeSlot,...] | None:
    """
    tìm 1 dãy tiết liên tiếp cho một sự kiện
    tham số:
    - time_slots: toàn bộ các tiết có thể sử dụng
    - day_of_week: ngày cần xếp
    - start_period: tiết bắt đầu
    - duration_periods: số tiết cần liên tiếp
    kết quả:
    trả về tuple các tiết liên tiếp nếu tìm thấy, hoặc None nếu không tìm thấy
    một dãy tiết hợp lệ phải có 
    đủ số tiết yêu cầu
    các period_number phải liên tiếp nhau
    tất cả các tiết phải cùng ngày, cùng 1 session 
    tất cả các tiết phải có teaching_event = True
    """
    if duration_periods <= 0:
        raise ValueError("duration_periods phải lớn hơn 0")
    """
    tạo bảng tra cứu timeslot gồm (day_of_week, period_number)
    ví dụ slot_lookup[(1, 2)]
    nghĩa là timeslot của thứ 2 tiết 1
    """
    slot_lookup: dict[tuple[int,int], TimeSlot] = {}
    # duyệt qua tất cả các timeslot để tạo bảng tra cứu
    for time_slot in time_slots:
        # tạo khóa từ ngày và số tiết 
        key=(
            time_slot.day_of_week,
            time_slot.period_number,
        )
        # lưu time slot và dictionary
        slot_lookup[key]=time_slot
    """
    tìm tiết bắt đầu ví dụ như day_of_week= 2 start period= 1
    """
    starting_slot = slot_lookup.get(
        (day_of_week, start_period)
    )
    if starting_slot is None:
        return None
    """
    tất cả các tiết sau phải cùng 1 session với tiết bắt đầu 
    ví dụ starting_session= SessionType.MORNING thì 1 time_slot AFTERNOON không được thêm vào 
    """
    start_session=starting_slot.session_type
    #danh sách tạm thời chứa các tiết hợp lệ
    selected_slots: list[TimeSlot]=[]
    # tạo các giá trị range duration period 
    # ví dụ duration_period=3 thì offset là 0 1 2
    for offset in range(duration_periods):
        """
        tính số tiết cần tìm 
        start period =2 :
        offset =0 thì curent_period =2
        '''''' 1 '''''''''''''''''''3
        '''''''2''''''''''''''''''''''4
        """
        current_period= start_period+offset

        """
        tìm time slot ứng với số ngày đang sét, số tiết hiện tại
        """
        current_slot=slot_lookup.get((day_of_week,current_period))
        if current_slot is None:
            return None
        """
        nếu teaching_slot =false thì nghĩa là khoảng này không dudwjowjc dùng để dạy
        ví dụ như giờ nghĩ giải lao...
        """
        if not current_slot.teaching_slot:
            return None
        """
        các tiết phải cùng 1 buổi khong được bắt đầu ở morning mà kéo sang afternoon
        """
        if current_slot.session_type != start_session:
            return None

        # tiết đạt điều kiện
        selected_slots.append(current_slot)
    return tuple(selected_slots)
def period_ranges_overlap(
        first_start_period: int,
        first_end_period: int,
        second_start_period: int,
        second_end_period: int
)-> bool:
    """
    kiểm tra 2 khoảng tiết có giao nhau hay không
    khoảng 1: first_start_period-> first_end_period
    khoảng 2: second_start_period-> second_end_period
    trả về true nếu 2 khoảng có ít nhất 1 tiết chung hoặc không thì fasle
    các tiết được tính bao gồm cả bắt đầu và kết thúc
    ví dụ 2-4 gồm tiết 2 3 4 và 4-6 gồm 4 5 6 giao nhau ở tiết 4
    """
    if first_start_period > first_end_period:
        raise ValueError("khoảng tiết thức nhất không hợp lệ")
    if second_start_period > second_end_period:
         raise ValueError(
            "Khoảng tiết thứ hai không hợp lệ."
        )
    """
    điều kiện thứ nhất:
    khoảng thứ nhất phải bắt đầu trước hoặc đúng lúc khoảng thứ 2 kết thúc
    ví dụ first start =2, second end=6 2<=6 true
    """
    first_starts_before_second_ends=(first_start_period <= second_end_period)
    """
    điều kiện thứ 2:
    khoảng thứ 2 phải bắt đầu trước hoặc đúng lúc khoảng thứ nhất kết thúc
    ví dụ second start=4 first end=5
    4<=5 true
    """
    second_starts_before_first_ends = (
        second_start_period <= first_end_period
    )
    # 2 khoảng chỉ giao nhau khi cả 2 đk đúng
    if(
        first_starts_before_second_ends and second_starts_before_first_ends
    ): 
        return True
    return False

def is_resource_unavailable(
        availability_windows: tuple[AvailabilityWindow,...],
        resource_index: int,
        day_of_week: int,
        start_period: int,
        end_period: int
)-> bool:
    """
    Kiểm tra một resource có bị UNAVAILABLE trong khoảng đang xét không.

    Resource có thể là:
    - Một giảng viên.
    - Một phòng học.

    Tham số:
    - availability_windows:
      Danh sách các khoảng khả dụng của resource.

    - resource_index:
      lecturer_index hoặc room_index cần kiểm tra.

    - day_of_week:
      Ngày của phương án đang xét.

    - start_period:
      Tiết bắt đầu của phương án.

    - end_period:
      Tiết kết thúc của phương án.

    Kết quả:
    - True:
      Resource bị UNAVAILABLE và không được sử dụng.

    - False:
      Không có khoảng UNAVAILABLE nào chặn phương án.

    """
    if start_period > end_period: 
        raise ValueError(
            "Khoảng tiết cần kiểm tra không hợp lệ."
        )
    for window in availability_windows:
        # nếu nó ở resource thì không liên quan bỏ qua
        if window.resource_index != resource_index:
            continue
        # nếu ở ngày khác bỏ qua
        if window.day_of_week != day_of_week:
            continue
        if(
            window.availability_type != AvailabilityType.UNAVAILABLE
        ): 
            continue
        # kiểm tra khoảng tiết của phương án có giao với khoảng tiết unavailiable hay kjhoong
        overlaps=period_ranges_overlap(
            first_start_period=start_period,
            first_end_period=end_period,
            second_start_period=window.start_period,
            second_end_period=window.end_period,
        )
        # nếu giao nhau thì bị cấm
        if overlaps:
            return True
    return False
    
def build_options_for_event(
        problem: ProblemInstance,
        event: TeachingEvent,
)-> tuple[CandidateOption,...]:
    """
    Tạo tất cả CandidateOption hợp lệ cho một TeachingEvent.

    Một CandidateOption chỉ được tạo khi:

    1. Có đủ dãy tiết liên tiếp.
    2. Các tiết nằm trong cùng một session.
    3. Tất cả các tiết có teaching_slot=True.
    4. Giảng viên không bị UNAVAILABLE.
    5. Phòng đang hoạt động.
    6. Phòng đủ sức chứa.
    7. Phòng đúng loại mà event yêu cầu.
    8. Phòng không bị UNAVAILABLE.

    Hàm trả về:
    - Một tuple chứa các CandidateOption hợp lệ.
    - Tuple rỗng nếu event không có phương án hợp lệ.

    Hàm chưa kiểm tra xung đột giữa nhiều event như:
    - Hai event dùng cùng phòng cùng lúc.
    - Giảng viên dạy hai event cùng lúc.
    - Nhóm sinh viên học hai event cùng lúc.

    Các xung đột giữa nhiều event sẽ được xử lý
    trong repair.py và fitness.py.
    """
    options: list[CandidateOption]=[]
    for starting_slot in problem.time_slots:
        """
        Tìm dãy tiết liên tiếp bắt đầu từ starting_slot.
        Ví dụ event cần 3 tiết và starting_slot là tiết 2: hàm sẽ cố tìm tiết 2, 3 và 4 trong cùng ngày, cùng session.
        """
        consecutive_slots=get_consecutive_time_slots(
            time_slots= problem.time_slots,
            day_of_week= starting_slot.day_of_week,
            start_period= starting_slot.period_number,
            duration_periods= event.duration_periods,
        )
        if consecutive_slots is None:
            continue
        # phần tử đầu tiên là tiết bắt đầu
        first_slot=consecutive_slots[0]
        # phần tử cuối là tiết kết thúc
        last_slot=consecutive_slots[-1]
        # lấy ngày của phương án
        option_day= first_slot.day_of_week
        # lấy số tiết bắt đầu
        option_start_period= first_slot.period_number
        # lấy số tiết kết thúc
        option_end_period=last_slot.period_number
        # lấy sesion của phương án
        option_session=first_slot.session_type
        # Kiểm tra giảng viên phụ trách event có bị UNAVAILABLE trong khoảng tiết này không.
        lecturer_is_unavailable=is_resource_unavailable(
            availability_windows= problem.lecturer_availabilities,
            resource_index= event.lecturer_index,
            day_of_week=option_day,
            start_period=option_start_period,
            end_period=option_end_period,
        )
        if lecturer_is_unavailable:
            continue
        for room in problem.rooms:
            # Kiểm tra:
            # - phòng có active không;
            # - phòng có đủ sức chứa không;
            # - phòng có đúng RoomType không.
            room_is_compatible=room_can_host_event(
                room=room,
                event=event,
            )
            if not room_is_compatible:
                continue
            

