package vn.edu.huit.timetabling_gapo.planning;

import java.util.List;

/** Một tổ hợp plan hữu hạn dùng để tạo một PlanningScenario ứng viên. */
public record GeneratedScenarioSelection(
        int candidateRank,
        int planRankPenalty,
        List<ScenarioPlanCandidate> plans
) {
    public GeneratedScenarioSelection {
        if (candidateRank <= 0 || planRankPenalty < 0) {
            throw new IllegalArgumentException("Thứ hạng scenario không hợp lệ.");
        }
        plans = List.copyOf(plans);
        if (plans.isEmpty()) {
            throw new IllegalArgumentException("Scenario phải chọn ít nhất một plan.");
        }
    }
}
