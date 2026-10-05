package vn.edu.huit.timetabling_gapo.planning;

/**
 * Một buổi dự kiến trong plan tự động, trước khi được mở rộng thành
 * ClassSession có định danh database.
 */
public record GeneratedTeachingPlanItem(
        int itemNumber,
        int weekNumber,
        int sessionOrderInWeek,
        int durationPeriods,
        int stabilityGroupNo
) {
    public GeneratedTeachingPlanItem {
        if (itemNumber < 1 || weekNumber < 1 || sessionOrderInWeek < 1) {
            throw new IllegalArgumentException("Số thứ tự item, tuần và buổi phải bắt đầu từ 1.");
        }
        if (durationPeriods < 1 || stabilityGroupNo < 1) {
            throw new IllegalArgumentException("Thời lượng và nhóm ổn định phải lớn hơn 0.");
        }
    }
}
