package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;

import java.util.List;
import java.util.Objects;

/** Một TeachingPlan hợp lệ được sinh hoàn toàn tự động từ rule đầu vào. */
public record GeneratedTeachingPlan(
        int sequenceNumber,
        String planCode,
        String planName,
        boolean intensive,
        List<GeneratedTeachingPlanItem> items
) {
    public GeneratedTeachingPlan {
        if (sequenceNumber < 1) {
            throw new IllegalArgumentException("Số thứ tự plan phải bắt đầu từ 1.");
        }
        if (planCode == null || planCode.isBlank() || planName == null || planName.isBlank()) {
            throw new IllegalArgumentException("Plan phải có mã và tên.");
        }
        items = List.copyOf(Objects.requireNonNull(items, "Danh sách buổi của plan không được null."));
        if (items.isEmpty()) {
            throw new IllegalArgumentException("Plan phải có ít nhất một buổi.");
        }
    }

    public int totalPeriods() {
        return items.stream().mapToInt(GeneratedTeachingPlanItem::durationPeriods).sum();
    }

    /**
     * Generator chỉ trả về kế hoạch đã vượt qua toàn bộ rule đầu vào, vì vậy
     * mọi kết quả sinh thành công đều có thể được lưu trực tiếp ở trạng thái
     * VALID. RETIRED chỉ được gán về sau bởi tầng persistence khi một kế hoạch
     * cũ không còn được sử dụng.
     */
    public TeachingPlanStatus status() {
        return TeachingPlanStatus.VALID;
    }
}
