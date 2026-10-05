package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.enums.LocationType;

/** Dữ liệu ClassSession sau khi mở rộng plan, trước bước persistence. */
public record ExpandedClassSession(
        int sessionNumber,
        int weekNumber,
        int durationPeriods,
        int stabilityGroupNo,
        LocationType requiredLocationType
) {
}
