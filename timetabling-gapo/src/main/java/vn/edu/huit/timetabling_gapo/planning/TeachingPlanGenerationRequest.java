package vn.edu.huit.timetabling_gapo.planning;

import java.util.List;
import java.util.Objects;

/**
 * Hợp đồng đầu vào bất biến của bộ sinh phương án giảng dạy.
 *
 * <p>Các giá trị trong record này đến từ TeachingPart, rule sinh plan và
 * TeachingDurationRule. Việc kiểm tra ngay tại biên giúp generator không phải
 * âm thầm sửa dữ liệu nghiệp vụ sai.</p>
 */
public record TeachingPlanGenerationRequest(
        String partCode,
        int totalPeriods,
        int startWeekNumber,
        int endWeekNumber,
        List<Integer> allowedDurations,
        int maxSessionsPerWeek,
        boolean allowsIntensive,
        int maxCandidatePlans
) {
    public TeachingPlanGenerationRequest {
        if (partCode == null || partCode.isBlank()) {
            throw new IllegalArgumentException("Mã phần giảng dạy không được để trống.");
        }
        if (totalPeriods <= 0) {
            throw new IllegalArgumentException("Tổng số tiết phải lớn hơn 0.");
        }
        if (startWeekNumber < 1 || endWeekNumber < startWeekNumber) {
            throw new IllegalArgumentException("Khoảng tuần được phép không hợp lệ.");
        }
        if (allowedDurations == null || allowedDurations.isEmpty()) {
            throw new IllegalArgumentException("Phải có ít nhất một thời lượng được phép.");
        }

        if (allowedDurations.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("Thời lượng được phép không được chứa null.");
        }

        allowedDurations = allowedDurations.stream()
                .distinct()
                .sorted()
                .toList();

        if (allowedDurations.stream().anyMatch(duration -> duration <= 0)) {
            throw new IllegalArgumentException("Mọi thời lượng được phép phải lớn hơn 0.");
        }
        if (maxSessionsPerWeek <= 0) {
            throw new IllegalArgumentException("Số buổi tối đa mỗi tuần phải lớn hơn 0.");
        }
        if (maxCandidatePlans <= 0) {
            throw new IllegalArgumentException("Số plan ứng viên tối đa phải lớn hơn 0.");
        }
    }

    public int weekCount() {
        return endWeekNumber - startWeekNumber + 1;
    }
}
