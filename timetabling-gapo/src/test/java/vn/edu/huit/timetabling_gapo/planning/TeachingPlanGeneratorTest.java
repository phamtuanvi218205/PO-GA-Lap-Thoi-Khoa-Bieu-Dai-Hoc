package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;

import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class TeachingPlanGeneratorTest {

    private final TeachingPlanGenerator generator = new TeachingPlanGenerator();

    @Test
    void generatesValidLecturePlansFromDiscreteRule() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "JAVA01_LT", 45, 1, 15, List.of(3, 6), 2, true, 100
        );

        List<GeneratedTeachingPlan> plans = generator.generate(request);

        assertFalse(plans.isEmpty());
        for (GeneratedTeachingPlan plan : plans) {
            assertEquals(TeachingPlanStatus.VALID, plan.status());
            assertEquals(45, plan.totalPeriods());
            assertTrue(plan.items().stream()
                    .allMatch(item -> item.weekNumber() >= 1 && item.weekNumber() <= 15));
            assertTrue(plan.items().stream()
                    .allMatch(item -> item.durationPeriods() == 3 || item.durationPeriods() == 6));

            Map<Integer, Long> sessionsPerWeek = plan.items().stream()
                    .collect(Collectors.groupingBy(
                            GeneratedTeachingPlanItem::weekNumber,
                            Collectors.counting()
                    ));
            assertTrue(sessionsPerWeek.values().stream().allMatch(count -> count <= 2));
        }

        assertTrue(plans.stream().anyMatch(plan ->
                plan.items().size() == 15
                        && plan.items().stream().allMatch(item -> item.durationPeriods() == 3)
                        && !plan.intensive()
        ));
        assertTrue(plans.stream().anyMatch(plan ->
                plan.items().stream().filter(item -> item.durationPeriods() == 3).count() == 5
                        && plan.items().stream().filter(item -> item.durationPeriods() == 6).count() == 5
        ));
    }

    @Test
    void generatesBothValidPracticeCompositions() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "JAVA01_TH", 30, 1, 15, List.of(5, 6), 1, true, 100
        );

        List<GeneratedTeachingPlan> plans = generator.generate(request);

        assertTrue(plans.stream().anyMatch(plan ->
                plan.items().size() == 6
                        && plan.items().stream().allMatch(item -> item.durationPeriods() == 5)
        ));
        assertTrue(plans.stream().anyMatch(plan ->
                plan.items().size() == 5
                        && plan.items().stream().allMatch(item -> item.durationPeriods() == 6)
        ));
        assertTrue(plans.stream().allMatch(plan -> plan.totalPeriods() == 30));
    }

    @Test
    void doesNotGenerateIntensiveVariantWhenRuleForbidsIt() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "JAVA01_LT", 45, 1, 15, List.of(3, 6), 1, false, 100
        );

        List<GeneratedTeachingPlan> plans = generator.generate(request);

        assertFalse(plans.isEmpty());
        assertTrue(plans.stream().noneMatch(GeneratedTeachingPlan::intensive));
        assertTrue(plans.stream().allMatch(plan ->
                plan.items().get(plan.items().size() - 1).weekNumber() == 15
        ));
    }

    @Test
    void returnsEmptyListWhenTotalCannotBeComposed() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "IMPOSSIBLE", 7, 1, 15, List.of(3, 6), 1, true, 20
        );

        assertTrue(generator.generate(request).isEmpty());
    }

    @Test
    void resultIsDeterministicAndContainsNoDuplicatePlan() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "JAVA01_LT", 45, 1, 15, List.of(6, 3, 3), 2, true, 100
        );

        List<GeneratedTeachingPlan> firstRun = generator.generate(request);
        List<GeneratedTeachingPlan> secondRun = generator.generate(request);

        assertEquals(firstRun, secondRun);
        Set<List<GeneratedTeachingPlanItem>> uniqueItems = new HashSet<>();
        assertTrue(firstRun.stream().map(GeneratedTeachingPlan::items).allMatch(uniqueItems::add));
    }

    @Test
    void respectsMaximumCandidatePlanCount() {
        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                "JAVA01_LT", 45, 1, 15, List.of(3, 6), 2, true, 3
        );

        List<GeneratedTeachingPlan> plans = generator.generate(request);

        assertEquals(3, plans.size());
        assertEquals(List.of(1, 2, 3), plans.stream()
                .map(GeneratedTeachingPlan::sequenceNumber)
                .toList());
    }

    @Test
    void validatesRequestAtTheBoundary() {
        assertThrows(IllegalArgumentException.class, () ->
                new TeachingPlanGenerationRequest(
                        "JAVA01_LT", 45, 15, 1, List.of(3, 6), 1, false, 20
                )
        );
        assertThrows(IllegalArgumentException.class, () ->
                new TeachingPlanGenerationRequest(
                        "JAVA01_LT", 45, 1, 15, List.of(3, 0), 1, false, 20
                )
        );
    }
}
