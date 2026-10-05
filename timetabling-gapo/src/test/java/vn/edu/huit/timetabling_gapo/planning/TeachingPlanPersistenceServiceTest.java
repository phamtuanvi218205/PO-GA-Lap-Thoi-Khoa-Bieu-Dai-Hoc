package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import vn.edu.huit.timetabling_gapo.entities.*;
import vn.edu.huit.timetabling_gapo.enums.*;
import vn.edu.huit.timetabling_gapo.repositories.*;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class TeachingPlanPersistenceServiceTest {

    @Test
    void generatesPersistsAndExpandsCurrentPlans() {
        Fixture fixture = new Fixture();
        TeachingPart part = fixture.part(45);
        TeachingPlanGenerationRule rule = fixture.rule(part);

        when(fixture.partRepository.findById(1L)).thenReturn(Optional.of(part));
        when(fixture.ruleRepository.findByTeachingPartTeachingPartIdAndActiveTrue(1L))
                .thenReturn(Optional.of(rule));
        when(fixture.durationRepository.findByPartTypeOrderByDurationPeriods(PartType.LECTURE))
                .thenReturn(List.of(fixture.duration(3), fixture.duration(6)));
        when(fixture.weekRepository.findByAcademicTermTermCodeOrderByWeekNumber("2026_HK1"))
                .thenReturn(fixture.weeks(15));
        when(fixture.planRepository
                .findByTeachingPartTeachingPartIdAndGenerationKeyOrderByCandidateRank(eq(1L), any()))
                .thenReturn(List.of());
        when(fixture.planRepository.findMaximumGenerationNo(1L)).thenReturn(0);
        when(fixture.planRepository.save(any(TeachingPlan.class))).thenAnswer(invocation -> {
            TeachingPlan plan = invocation.getArgument(0);
            plan.setTeachingPlanId((long) plan.getCandidateRank());
            return plan;
        });
        when(fixture.planRepository
                .findByTeachingPartTeachingPartIdAndStatusOrderByCandidateRank(
                        1L,
                        TeachingPlanStatus.VALID
                ))
                .thenReturn(List.of());

        List<TeachingPlan> plans = fixture.service().ensureCurrentPlans(1L);

        assertFalse(plans.isEmpty());
        assertTrue(plans.stream().allMatch(plan -> plan.getStatus() == TeachingPlanStatus.VALID));
        assertTrue(plans.stream().allMatch(plan -> plan.getGenerationNo() == 1));
        assertTrue(plans.stream().allMatch(plan -> plan.getGenerationKey().length() == 64));
        verify(fixture.itemRepository, times(plans.size())).saveAll(any());
        verify(fixture.sessionRepository, times(plans.size())).saveAll(any());
    }

    @Test
    void reusesSameGenerationAndRetiresOnlyUnlockedOlderPlans() {
        Fixture fixture = new Fixture();
        TeachingPart part = fixture.part(3);
        TeachingPlanGenerationRule rule = fixture.rule(part);
        List<Integer> durations = List.of(3, 6);
        String key = PlanGenerationKeyFactory.create(part, rule, durations);

        TeachingPlan current = fixture.plan(part, 10L, key, 2, 1);
        current.setStatus(TeachingPlanStatus.RETIRED);
        TeachingPlan lockedOld = fixture.plan(part, 20L, "A".repeat(64), 1, 1);
        TeachingPlan unlockedOld = fixture.plan(part, 30L, "B".repeat(64), 1, 2);

        when(fixture.partRepository.findById(1L)).thenReturn(Optional.of(part));
        when(fixture.ruleRepository.findByTeachingPartTeachingPartIdAndActiveTrue(1L))
                .thenReturn(Optional.of(rule));
        when(fixture.durationRepository.findByPartTypeOrderByDurationPeriods(PartType.LECTURE))
                .thenReturn(List.of(fixture.duration(3), fixture.duration(6)));
        when(fixture.weekRepository.findByAcademicTermTermCodeOrderByWeekNumber("2026_HK1"))
                .thenReturn(fixture.weeks(15));
        when(fixture.planRepository
                .findByTeachingPartTeachingPartIdAndGenerationKeyOrderByCandidateRank(1L, key))
                .thenReturn(List.of(current));
        TeachingPlanItem currentItem = fixture.item(current, 1, 3);
        ClassSession currentSession = fixture.session(current, 1, 3);
        when(fixture.itemRepository
                .findByTeachingPlanTeachingPlanIdOrderByItemNumber(10L))
                .thenReturn(List.of(currentItem));
        when(fixture.sessionRepository
                .findByTeachingPlanTeachingPlanIdOrderBySessionNumber(10L))
                .thenReturn(List.of(currentSession));
        when(fixture.planRepository
                .findByTeachingPartTeachingPartIdAndStatusOrderByCandidateRank(
                        1L,
                        TeachingPlanStatus.VALID
                ))
                .thenReturn(List.of(current, lockedOld, unlockedOld));
        when(fixture.scenarioItemRepository
                .existsByTeachingPlanTeachingPlanIdAndPlanningScenarioStatus(
                        20L,
                        PlanningScenarioStatus.LOCKED
                ))
                .thenReturn(true);
        when(fixture.scenarioItemRepository
                .existsByTeachingPlanTeachingPlanIdAndPlanningScenarioStatus(
                        30L,
                        PlanningScenarioStatus.LOCKED
                ))
                .thenReturn(false);

        List<TeachingPlan> result = fixture.service().ensureCurrentPlans(1L);

        assertEquals(List.of(current), result);
        assertEquals(TeachingPlanStatus.VALID, current.getStatus());
        assertEquals(TeachingPlanStatus.VALID, lockedOld.getStatus());
        assertEquals(TeachingPlanStatus.RETIRED, unlockedOld.getStatus());
        verify(fixture.generator, never()).generate(any());
        verify(fixture.itemRepository, never()).saveAll(any());
        verify(fixture.sessionRepository, never()).saveAll(any());
    }

    @Test
    void rejectsCorruptedExistingGenerationInsteadOfSilentlyReusingIt() {
        Fixture fixture = new Fixture();
        TeachingPart part = fixture.part(3);
        TeachingPlanGenerationRule rule = fixture.rule(part);
        String key = PlanGenerationKeyFactory.create(part, rule, List.of(3, 6));
        TeachingPlan current = fixture.plan(part, 10L, key, 1, 1);

        when(fixture.partRepository.findById(1L)).thenReturn(Optional.of(part));
        when(fixture.ruleRepository.findByTeachingPartTeachingPartIdAndActiveTrue(1L))
                .thenReturn(Optional.of(rule));
        when(fixture.durationRepository.findByPartTypeOrderByDurationPeriods(PartType.LECTURE))
                .thenReturn(List.of(fixture.duration(3), fixture.duration(6)));
        when(fixture.weekRepository.findByAcademicTermTermCodeOrderByWeekNumber("2026_HK1"))
                .thenReturn(fixture.weeks(15));
        when(fixture.planRepository
                .findByTeachingPartTeachingPartIdAndGenerationKeyOrderByCandidateRank(1L, key))
                .thenReturn(List.of(current));
        when(fixture.itemRepository
                .findByTeachingPlanTeachingPlanIdOrderByItemNumber(10L))
                .thenReturn(List.of());
        when(fixture.sessionRepository
                .findByTeachingPlanTeachingPlanIdOrderBySessionNumber(10L))
                .thenReturn(List.of());

        IllegalStateException exception = assertThrows(
                IllegalStateException.class,
                () -> fixture.service().ensureCurrentPlans(1L)
        );

        assertTrue(exception.getMessage().contains("thiếu TeachingPlanItem"));
        verify(fixture.generator, never()).generate(any());
    }

    private static final class Fixture {
        private final TeachingPartRepository partRepository = mock(TeachingPartRepository.class);
        private final TeachingPlanGenerationRuleRepository ruleRepository =
                mock(TeachingPlanGenerationRuleRepository.class);
        private final TeachingDurationRuleRepository durationRepository =
                mock(TeachingDurationRuleRepository.class);
        private final TermWeekRepository weekRepository = mock(TermWeekRepository.class);
        private final TeachingPlanRepository planRepository = mock(TeachingPlanRepository.class);
        private final TeachingPlanItemRepository itemRepository = mock(TeachingPlanItemRepository.class);
        private final ClassSessionRepository sessionRepository = mock(ClassSessionRepository.class);
        private final PlanningScenarioItemRepository scenarioItemRepository =
                mock(PlanningScenarioItemRepository.class);
        private final TeachingPlanGenerator generator = spy(new TeachingPlanGenerator());
        private final SessionExpander expander = new SessionExpander();

        private TeachingPlanPersistenceService service() {
            return new TeachingPlanPersistenceService(
                    partRepository,
                    ruleRepository,
                    durationRepository,
                    weekRepository,
                    planRepository,
                    itemRepository,
                    sessionRepository,
                    scenarioItemRepository,
                    generator,
                    expander
            );
        }

        private TeachingPart part(int totalPeriods) {
            AcademicTerm term = new AcademicTerm();
            term.setTermCode("2026_HK1");
            CourseSection section = new CourseSection();
            section.setSectionCode("JAVA01");
            section.setAcademicTerm(term);
            section.setStatus(CourseSectionStatus.APPROVED);

            TeachingPart part = new TeachingPart();
            part.setTeachingPartId(1L);
            part.setPartCode("JAVA01_LT");
            part.setPartType(PartType.LECTURE);
            part.setTotalPeriods(totalPeriods);
            part.setRequiredLocationType(LocationType.PHYSICAL_ROOM);
            part.setCourseSection(section);
            return part;
        }

        private TeachingPlanGenerationRule rule(TeachingPart part) {
            TeachingPlanGenerationRule rule = new TeachingPlanGenerationRule();
            rule.setTeachingPart(part);
            rule.setStartWeekNumber(1);
            rule.setEndWeekNumber(15);
            rule.setMaxSessionsPerWeek(2);
            rule.setAllowsIntensive(true);
            rule.setMaxCandidatePlans(5);
            rule.setActive(true);
            return rule;
        }

        private TeachingDurationRule duration(int value) {
            TeachingDurationRule rule = new TeachingDurationRule();
            rule.setPartType(PartType.LECTURE);
            rule.setDurationPeriods(value);
            rule.setStandard(true);
            return rule;
        }

        private List<TermWeek> weeks(int count) {
            AcademicTerm term = new AcademicTerm();
            term.setTermCode("2026_HK1");
            return java.util.stream.IntStream.rangeClosed(1, count)
                    .mapToObj(number -> {
                        TermWeek week = new TermWeek();
                        week.setAcademicTerm(term);
                        week.setWeekNumber(number);
                        week.setStartDate(LocalDate.of(2026, 8, 31).plusWeeks(number - 1L));
                        week.setEndDate(week.getStartDate().plusDays(6));
                        return week;
                    })
                    .toList();
        }

        private TeachingPlan plan(
                TeachingPart part,
                Long id,
                String key,
                int generationNo,
                int rank
        ) {
            TeachingPlan plan = new TeachingPlan();
            plan.setTeachingPlanId(id);
            plan.setTeachingPart(part);
            plan.setPlanCode("PLAN_" + id);
            plan.setPlanName("Plan " + id);
            plan.setStatus(TeachingPlanStatus.VALID);
            plan.setAllowsIntensive(false);
            plan.setGenerationNo(generationNo);
            plan.setCandidateRank(rank);
            plan.setGenerationKey(key);
            return plan;
        }

        private TeachingPlanItem item(TeachingPlan plan, int number, int duration) {
            TermWeek week = weeks(1).getFirst();
            TeachingPlanItem item = new TeachingPlanItem();
            item.setTeachingPlan(plan);
            item.setItemNumber(number);
            item.setTermWeek(week);
            item.setSessionOrderInWeek(1);
            item.setDurationPeriods(duration);
            item.setStabilityGroupNo(1);
            return item;
        }

        private ClassSession session(TeachingPlan plan, int number, int duration) {
            TermWeek week = weeks(1).getFirst();
            ClassSession session = new ClassSession();
            session.setTeachingPlan(plan);
            session.setSessionNumber(number);
            session.setTermWeek(week);
            session.setDurationPeriods(duration);
            session.setStabilityGroupNo(1);
            return session;
        }
    }
}
