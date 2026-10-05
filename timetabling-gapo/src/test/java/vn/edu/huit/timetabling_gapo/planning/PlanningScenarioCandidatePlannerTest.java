package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class PlanningScenarioCandidatePlannerTest {

    private final PlanningScenarioCandidatePlanner planner = new PlanningScenarioCandidatePlanner();

    @Test
    void startsWithRankOnePlansAndGeneratesOnlyRequestedNumberOfVariants() {
        Map<Long, List<ScenarioPlanCandidate>> candidates = new LinkedHashMap<>();
        candidates.put(1L, List.of(
                new ScenarioPlanCandidate(1, 11, 1, false),
                new ScenarioPlanCandidate(1, 12, 2, true),
                new ScenarioPlanCandidate(1, 13, 3, true)
        ));
        candidates.put(2L, List.of(
                new ScenarioPlanCandidate(2, 21, 1, false),
                new ScenarioPlanCandidate(2, 22, 2, false)
        ));

        List<GeneratedScenarioSelection> selections = planner.generate(candidates, 4);

        assertEquals(4, selections.size());
        assertEquals(List.of(11L, 21L), planIds(selections.getFirst()));
        assertEquals(0, selections.getFirst().planRankPenalty());
        assertEquals(List.of(1, 2, 3, 4), selections.stream()
                .map(GeneratedScenarioSelection::candidateRank)
                .toList());
        assertTrue(selections.stream().allMatch(selection -> selection.plans().size() == 2));
    }

    @Test
    void remainsBoundedInsteadOfBuildingTheWholeCartesianProduct() {
        Map<Long, List<ScenarioPlanCandidate>> candidates = new LinkedHashMap<>();
        for (long partId = 1; partId <= 20; partId++) {
            List<ScenarioPlanCandidate> plans = new java.util.ArrayList<>();
            for (int rank = 1; rank <= 20; rank++) {
                plans.add(new ScenarioPlanCandidate(
                        partId,
                        partId * 1_000 + rank,
                        rank,
                        rank > 10
                ));
            }
            candidates.put(partId, plans);
        }

        List<GeneratedScenarioSelection> selections = planner.generate(candidates, 10);

        assertEquals(10, selections.size());
        assertTrue(selections.stream().allMatch(selection -> selection.plans().size() == 20));
        assertEquals(0, selections.getFirst().planRankPenalty());
    }

    @Test
    void sameInputProducesTheSameSelections() {
        Map<Long, List<ScenarioPlanCandidate>> candidates = Map.of(
                2L, List.of(
                        new ScenarioPlanCandidate(2, 22, 2, true),
                        new ScenarioPlanCandidate(2, 21, 1, false)
                ),
                1L, List.of(
                        new ScenarioPlanCandidate(1, 12, 2, false),
                        new ScenarioPlanCandidate(1, 11, 1, false)
                )
        );

        assertEquals(planner.generate(candidates, 4), planner.generate(candidates, 4));
    }

    @Test
    void rejectsMissingCandidatesAndInvalidLimit() {
        assertThrows(IllegalArgumentException.class, () -> planner.generate(Map.of(), 1));
        assertThrows(IllegalArgumentException.class, () -> planner.generate(
                Map.of(1L, List.of()),
                1
        ));
        assertThrows(IllegalArgumentException.class, () -> planner.generate(
                Map.of(1L, List.of(new ScenarioPlanCandidate(1, 11, 1, false))),
                0
        ));
    }

    private List<Long> planIds(GeneratedScenarioSelection selection) {
        return selection.plans().stream()
                .map(ScenarioPlanCandidate::teachingPlanId)
                .toList();
    }
}
