package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.enums.LocationType;

/**
 * Một lần xuất hiện theo tuần sau khi mở rộng plan, trước persistence.
 * stabilityGroupNo liên kết các tuần phải dùng chung mẫu lịch cố định.
 */
public record ExpandedClassSession(
        int sessionNumber,
        int weekNumber,
        int durationPeriods,
        int stabilityGroupNo,
        LocationType requiredLocationType
) {
}
