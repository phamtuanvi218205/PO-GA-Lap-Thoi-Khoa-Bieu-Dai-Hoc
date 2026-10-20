package vn.edu.huit.timetabling_gapo.planning;

import org.springframework.stereotype.Component;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

import java.util.List;

/**
 * Chuyển các item của một plan hợp lệ thành các lần xuất hiện theo tuần.
 * Những lần xuất hiện có cùng stabilityGroupNo tạo một chuỗi lặp và sẽ dùng
 * chung một gene thứ-tiết-địa điểm trong optimizer. Lớp này không chọn lịch.
 */
@Component
public class SessionExpander {

    public List<ExpandedClassSession> expand(
            GeneratedTeachingPlan plan,
            LocationType requiredLocationType
    ) {
        if (plan == null) {
            throw new IllegalArgumentException("Plan không được null.");
        }
        if (requiredLocationType == null) {
            throw new IllegalArgumentException("Loại địa điểm không được null.");
        }

        return plan.items().stream()
                .map(item -> new ExpandedClassSession(
                        item.itemNumber(),
                        item.weekNumber(),
                        item.durationPeriods(),
                        item.stabilityGroupNo(),
                        requiredLocationType
                ))
                .toList();
    }
}
