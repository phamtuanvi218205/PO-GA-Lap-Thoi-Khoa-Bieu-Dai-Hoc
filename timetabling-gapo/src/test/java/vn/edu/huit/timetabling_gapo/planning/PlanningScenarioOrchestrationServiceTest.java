package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;
import vn.edu.huit.timetabling_gapo.entities.*;
import vn.edu.huit.timetabling_gapo.enums.*;
import vn.edu.huit.timetabling_gapo.repositories.*;

import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class PlanningScenarioOrchestrationServiceTest {

    @Test
    void createsReadyThenLockedScenarioFromStructurallyValidPlans() {
        AcademicTermRepository termRepository = mock(AcademicTermRepository.class);
        TeachingPartRepository partRepository = mock(TeachingPartRepository.class);
        ClassSessionRepository sessionRepository = mock(ClassSessionRepository.class);
        PlanningScenarioRepository scenarioRepository = mock(PlanningScenarioRepository.class);
        PlanningScenarioItemRepository itemRepository = mock(PlanningScenarioItemRepository.class);
        TeachingPlanPersistenceService persistenceService = mock(TeachingPlanPersistenceService.class);

        AcademicTerm term = new AcademicTerm();
        term.setTermCode("2026_HK1");
        CourseSection section = new CourseSection();
        section.setSectionCode("JAVA01");
        section.setAcademicTerm(term);
        section.setStatus(CourseSectionStatus.APPROVED);
        Lecturer lecturer = new Lecturer();
        lecturer.setLecturerCode("GV01");
        TeachingPart part = new TeachingPart();
        part.setTeachingPartId(1L);
        part.setPartCode("JAVA01_LT");
        part.setTotalPeriods(3);
        part.setCourseSection(section);
        part.setLecturer(lecturer);

        TeachingPlan plan = new TeachingPlan();
        plan.setTeachingPlanId(10L);
        plan.setTeachingPart(part);
        plan.setPlanCode("JAVA01_LT_G001_P01");
        plan.setStatus(TeachingPlanStatus.VALID);
        plan.setCandidateRank(1);
        plan.setAllowsIntensive(false);

        TermWeek week = new TermWeek();
        week.setAcademicTerm(term);
        week.setWeekNumber(1);
        ClassSession session = new ClassSession();
        session.setTeachingPlan(plan);
        session.setSessionNumber(1);
        session.setTermWeek(week);
        session.setDurationPeriods(3);

        when(termRepository.findById("2026_HK1")).thenReturn(Optional.of(term));
        when(partRepository
                .findByCourseSectionAcademicTermTermCodeAndCourseSectionStatusOrderByPartCode(
                        "2026_HK1",
                        CourseSectionStatus.APPROVED
                ))
                .thenReturn(List.of(part));
        when(persistenceService.ensureCurrentPlans(1L)).thenReturn(List.of(plan));
        when(sessionRepository.findByTeachingPlanTeachingPlanIdOrderBySessionNumber(10L))
                .thenReturn(List.of(session));
        when(scenarioRepository.save(any(PlanningScenario.class))).thenAnswer(invocation -> {
            PlanningScenario scenario = invocation.getArgument(0);
            scenario.setScenarioId(100L);
            return scenario;
        });
        when(scenarioRepository.saveAndFlush(any(PlanningScenario.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        PlanningScenarioOrchestrationService service =
                new PlanningScenarioOrchestrationService(
                        termRepository,
                        partRepository,
                        sessionRepository,
                        scenarioRepository,
                        itemRepository,
                        persistenceService,
                        new PlanningScenarioCandidatePlanner()
                );

        List<PlanningScenario> scenarios = service.createAndLockCandidates(
                new AutomaticScenarioRequest(
                        "2026_HK1",
                        ScenarioScopeType.FULL_TERM,
                        Set.of(),
                        10
                )
        );

        assertEquals(1, scenarios.size());
        PlanningScenario scenario = scenarios.getFirst();
        assertEquals(PlanningScenarioStatus.LOCKED, scenario.getStatus());
        assertEquals("SYSTEM", scenario.getCreatedBy());
        assertEquals("SYSTEM", scenario.getLockedBy());
        assertNotNull(scenario.getLockedAt());
        assertEquals(1, scenario.getCandidateRank());
        assertEquals(0, scenario.getPlanRankPenalty());
        verify(itemRepository).saveAll(any());
        verify(scenarioRepository, times(2)).saveAndFlush(scenario);
    }

    @Test
    void validatesSubsetRequestAtTheBoundary() {
        assertThrows(IllegalArgumentException.class, () -> new AutomaticScenarioRequest(
                "2026_HK1",
                ScenarioScopeType.SUBSET,
                Set.of(),
                10
        ));
        assertThrows(IllegalArgumentException.class, () -> new AutomaticScenarioRequest(
                "2026_HK1",
                ScenarioScopeType.FULL_TERM,
                Set.of(1L),
                10
        ));
    }

    @Test
    void rejectsScenarioWhenPartsOfSameSectionUseDifferentLecturers() {
        AcademicTermRepository termRepository = mock(AcademicTermRepository.class);
        TeachingPartRepository partRepository = mock(TeachingPartRepository.class);
        ClassSessionRepository sessionRepository = mock(ClassSessionRepository.class);
        PlanningScenarioRepository scenarioRepository = mock(PlanningScenarioRepository.class);
        PlanningScenarioItemRepository itemRepository = mock(PlanningScenarioItemRepository.class);
        TeachingPlanPersistenceService persistenceService = mock(TeachingPlanPersistenceService.class);

        AcademicTerm term = new AcademicTerm();
        term.setTermCode("2026_HK1");
        CourseSection section = new CourseSection();
        section.setSectionCode("JAVA01");
        section.setAcademicTerm(term);
        section.setStatus(CourseSectionStatus.APPROVED);

        Lecturer firstLecturer = new Lecturer();
        firstLecturer.setLecturerCode("GV01");
        Lecturer secondLecturer = new Lecturer();
        secondLecturer.setLecturerCode("GV02");

        TeachingPart lecture = new TeachingPart();
        lecture.setTeachingPartId(1L);
        lecture.setPartCode("JAVA01_LT");
        lecture.setCourseSection(section);
        lecture.setLecturer(firstLecturer);
        TeachingPart practice = new TeachingPart();
        practice.setTeachingPartId(2L);
        practice.setPartCode("JAVA01_TH");
        practice.setCourseSection(section);
        practice.setLecturer(secondLecturer);

        when(termRepository.findById("2026_HK1")).thenReturn(Optional.of(term));
        when(partRepository
                .findByCourseSectionAcademicTermTermCodeAndCourseSectionStatusOrderByPartCode(
                        "2026_HK1",
                        CourseSectionStatus.APPROVED
                ))
                .thenReturn(List.of(lecture, practice));

        PlanningScenarioOrchestrationService service =
                new PlanningScenarioOrchestrationService(
                        termRepository,
                        partRepository,
                        sessionRepository,
                        scenarioRepository,
                        itemRepository,
                        persistenceService,
                        new PlanningScenarioCandidatePlanner()
                );

        IllegalStateException exception = assertThrows(
                IllegalStateException.class,
                () -> service.createAndLockCandidates(new AutomaticScenarioRequest(
                        "2026_HK1",
                        ScenarioScopeType.FULL_TERM,
                        Set.of(),
                        10
                ))
        );

        assertTrue(exception.getMessage().contains("phải dùng chung một giảng viên"));
        verifyNoInteractions(persistenceService);
    }
}
