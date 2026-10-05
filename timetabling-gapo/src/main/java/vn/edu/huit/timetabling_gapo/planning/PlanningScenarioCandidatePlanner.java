package vn.edu.huit.timetabling_gapo.planning;

import org.springframework.stereotype.Component;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Sinh hữu hạn các tổ hợp plan tốt nhất mà không tạo toàn bộ tích Descartes.
 * Tổ hợp cơ sở luôn dùng plan hạng 1 của mỗi TeachingPart; các tổ hợp sau lùi
 * dần sang plan hạng thấp hơn theo tổng mức phạt nhỏ nhất.
 */
@Component
public class PlanningScenarioCandidatePlanner {

    public List<GeneratedScenarioSelection> generate(
            Map<Long, List<ScenarioPlanCandidate>> candidatesByPart,
            int maxScenarioCandidates
    ) {
        if (candidatesByPart == null || candidatesByPart.isEmpty()) {
            throw new IllegalArgumentException("Phải có plan ứng viên cho ít nhất một TeachingPart.");
        }
        if (maxScenarioCandidates <= 0) {
            throw new IllegalArgumentException("Số scenario ứng viên tối đa phải lớn hơn 0.");
        }

        List<Long> partIds = candidatesByPart.keySet().stream().sorted().toList();
        List<List<ScenarioPlanCandidate>> orderedCandidates = new ArrayList<>(partIds.size());
        for (Long partId : partIds) {
            List<ScenarioPlanCandidate> plans = candidatesByPart.get(partId).stream()
                    .sorted(Comparator
                            .comparingInt(ScenarioPlanCandidate::candidateRank)
                            .thenComparing(ScenarioPlanCandidate::intensive)
                            .thenComparingLong(ScenarioPlanCandidate::teachingPlanId))
                    .toList();
            if (plans.isEmpty()) {
                throw new IllegalArgumentException("TeachingPart " + partId + " không có plan VALID.");
            }
            if (plans.stream().anyMatch(plan -> plan.teachingPartId() != partId)) {
                throw new IllegalArgumentException("Danh sách plan không thuộc đúng TeachingPart " + partId + ".");
            }
            orderedCandidates.add(plans);
        }

        Comparator<IndexState> stateComparator = Comparator
                .comparingInt((IndexState state) -> penalty(state, orderedCandidates))
                .thenComparingInt(state -> intensiveCount(state, orderedCandidates))
                .thenComparing(IndexState::signature);
        PriorityQueue<IndexState> queue = new PriorityQueue<>(stateComparator);
        Set<String> visited = new HashSet<>();
        IndexState initial = new IndexState(new int[partIds.size()]);
        queue.add(initial);
        visited.add(initial.signature());

        List<GeneratedScenarioSelection> result = new ArrayList<>();
        while (!queue.isEmpty() && result.size() < maxScenarioCandidates) {
            IndexState state = queue.remove();
            List<ScenarioPlanCandidate> selection = new ArrayList<>(partIds.size());
            for (int partIndex = 0; partIndex < partIds.size(); partIndex++) {
                selection.add(orderedCandidates.get(partIndex).get(state.indexes()[partIndex]));
            }
            result.add(new GeneratedScenarioSelection(
                    result.size() + 1,
                    penalty(state, orderedCandidates),
                    selection
            ));

            for (int partIndex = 0; partIndex < partIds.size(); partIndex++) {
                int nextIndex = state.indexes()[partIndex] + 1;
                if (nextIndex >= orderedCandidates.get(partIndex).size()) {
                    continue;
                }
                int[] neighborIndexes = state.indexes().clone();
                neighborIndexes[partIndex] = nextIndex;
                IndexState neighbor = new IndexState(neighborIndexes);
                if (visited.add(neighbor.signature())) {
                    queue.add(neighbor);
                }
            }
        }
        return List.copyOf(result);
    }

    private static int penalty(
            IndexState state,
            List<List<ScenarioPlanCandidate>> orderedCandidates
    ) {
        int total = 0;
        for (int partIndex = 0; partIndex < state.indexes().length; partIndex++) {
            ScenarioPlanCandidate candidate = orderedCandidates
                    .get(partIndex)
                    .get(state.indexes()[partIndex]);
            total += candidate.candidateRank() - 1;
        }
        return total;
    }

    private static int intensiveCount(
            IndexState state,
            List<List<ScenarioPlanCandidate>> orderedCandidates
    ) {
        int count = 0;
        for (int partIndex = 0; partIndex < state.indexes().length; partIndex++) {
            if (orderedCandidates.get(partIndex).get(state.indexes()[partIndex]).intensive()) {
                count++;
            }
        }
        return count;
    }

    private record IndexState(int[] indexes) {
        private String signature() {
            return Arrays.stream(indexes)
                    .mapToObj(String::valueOf)
                    .collect(Collectors.joining(","));
        }
    }
}
