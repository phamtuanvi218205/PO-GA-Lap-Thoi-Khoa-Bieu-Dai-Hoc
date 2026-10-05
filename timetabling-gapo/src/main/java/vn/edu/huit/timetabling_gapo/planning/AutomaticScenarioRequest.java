package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.enums.ScenarioScopeType;

import java.util.Set;

/** Hợp đồng tạo hữu hạn PlanningScenario hoàn toàn tự động. */
public record AutomaticScenarioRequest(
        String termCode,
        ScenarioScopeType scopeType,
        Set<Long> teachingPartIds,
        int maxScenarioCandidates
) {
    public static final int DEFAULT_MAX_SCENARIO_CANDIDATES = 10;

    public AutomaticScenarioRequest(
            String termCode,
            ScenarioScopeType scopeType,
            Set<Long> teachingPartIds
    ) {
        this(termCode, scopeType, teachingPartIds, DEFAULT_MAX_SCENARIO_CANDIDATES);
    }

    public AutomaticScenarioRequest {
        if (termCode == null || termCode.isBlank() || scopeType == null) {
            throw new IllegalArgumentException("Học kỳ và phạm vi scenario là bắt buộc.");
        }
        teachingPartIds = teachingPartIds == null ? Set.of() : Set.copyOf(teachingPartIds);
        if (scopeType == ScenarioScopeType.SUBSET && teachingPartIds.isEmpty()) {
            throw new IllegalArgumentException("Scenario SUBSET phải chỉ rõ TeachingPart.");
        }
        if (scopeType == ScenarioScopeType.FULL_TERM && !teachingPartIds.isEmpty()) {
            throw new IllegalArgumentException("Scenario FULL_TERM tự lấy toàn bộ phần giảng dạy được công bố.");
        }
        if (maxScenarioCandidates <= 0) {
            throw new IllegalArgumentException("Số scenario ứng viên tối đa phải lớn hơn 0.");
        }
    }
}
