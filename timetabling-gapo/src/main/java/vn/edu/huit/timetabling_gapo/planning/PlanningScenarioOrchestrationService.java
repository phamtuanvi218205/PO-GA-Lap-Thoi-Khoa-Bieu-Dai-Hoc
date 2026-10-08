package vn.edu.huit.timetabling_gapo.planning;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.edu.huit.timetabling_gapo.entities.*;
import vn.edu.huit.timetabling_gapo.enums.*;
import vn.edu.huit.timetabling_gapo.repositories.*;

import java.time.LocalDateTime;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/** Tạo, kiểm tra và khóa hữu hạn các PlanningScenario ứng viên. */
@Service
@RequiredArgsConstructor
public class PlanningScenarioOrchestrationService {

    private static final String SYSTEM_ACTOR = "SYSTEM";

    private final AcademicTermRepository academicTermRepository;
    private final TeachingPartRepository teachingPartRepository;
    private final ClassSessionRepository classSessionRepository;
    private final PlanningScenarioRepository scenarioRepository;
    private final PlanningScenarioItemRepository scenarioItemRepository;
    private final TeachingPlanPersistenceService planPersistenceService;
    private final PlanningScenarioCandidatePlanner candidatePlanner;

    @Transactional
    public List<PlanningScenario> createAndLockCandidates(AutomaticScenarioRequest request) {
        AcademicTerm term = academicTermRepository.findById(request.termCode())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Không tìm thấy học kỳ " + request.termCode() + "."));
        List<TeachingPart> parts = loadParts(request);
        if (parts.isEmpty()) {
            throw new IllegalStateException("Phạm vi scenario không có TeachingPart nào.");
        }
        TeachingAssignmentPolicy.requireOneLecturerPerCourseSection(parts);

        Map<Long, TeachingPart> partsById = parts.stream().collect(Collectors.toMap(
                TeachingPart::getTeachingPartId,
                Function.identity()
        ));
        Map<Long, TeachingPlan> plansById = new HashMap<>();
        Map<Long, List<ScenarioPlanCandidate>> candidatesByPart = new TreeMap<>();
        for (TeachingPart part : parts) {
            List<TeachingPlan> currentPlans = planPersistenceService
                    .ensureCurrentPlans(part.getTeachingPartId());
            List<ScenarioPlanCandidate> candidates = currentPlans.stream()
                    .filter(plan -> plan.getStatus() == TeachingPlanStatus.VALID)
                    .map(plan -> {
                        plansById.put(plan.getTeachingPlanId(), plan);
                        return new ScenarioPlanCandidate(
                                part.getTeachingPartId(),
                                plan.getTeachingPlanId(),
                                plan.getCandidateRank(),
                                Boolean.TRUE.equals(plan.getAllowsIntensive())
                        );
                    })
                    .toList();
            if (candidates.isEmpty()) {
                throw new IllegalStateException(
                        "TeachingPart " + part.getPartCode() + " không có plan VALID hiện hành.");
            }
            candidatesByPart.put(part.getTeachingPartId(), candidates);
        }

        List<GeneratedScenarioSelection> selections = candidatePlanner.generate(
                candidatesByPart,
                request.maxScenarioCandidates()
        );
        String batchCode = buildBatchCode(request.termCode());
        LocalDateTime now = LocalDateTime.now();
        List<PlanningScenario> scenarios = new ArrayList<>(selections.size());

        for (GeneratedScenarioSelection selection : selections) {
            PlanningScenario scenario = new PlanningScenario();
            scenario.setScenarioCode("%s_V%02d".formatted(batchCode, selection.candidateRank()));
            scenario.setScenarioName("Tự động %s - phương án %02d"
                    .formatted(request.termCode(), selection.candidateRank()));
            scenario.setAcademicTerm(term);
            scenario.setScopeType(request.scopeType());
            scenario.setStatus(PlanningScenarioStatus.DRAFT);
            scenario.setScenarioBatchCode(batchCode);
            scenario.setCandidateRank(selection.candidateRank());
            scenario.setPlanRankPenalty(selection.planRankPenalty());
            scenario.setCreatedBy(SYSTEM_ACTOR);
            scenario.setCreatedAt(now);
            scenario.setNote("Scenario được hệ thống tạo tự động từ các plan VALID.");
            PlanningScenario savedScenario = scenarioRepository.save(scenario);

            List<PlanningScenarioItem> items = selection.plans().stream()
                    .map(candidate -> new PlanningScenarioItem(
                            savedScenario,
                            requirePart(partsById, candidate.teachingPartId()),
                            requirePlan(plansById, candidate.teachingPlanId())
                    ))
                    .toList();
            scenarioItemRepository.saveAll(items);

            try {
                validateStructure(savedScenario, items, request.termCode(), parts.size());
                savedScenario.setStatus(PlanningScenarioStatus.READY);
                scenarioRepository.saveAndFlush(savedScenario);
                savedScenario.setStatus(PlanningScenarioStatus.LOCKED);
                savedScenario.setLockedBy(SYSTEM_ACTOR);
                savedScenario.setLockedAt(LocalDateTime.now());
                savedScenario.setNote(
                        "Đã tự kiểm tra đủ plan/session và khóa dữ liệu. "
                                + "Miền SessionOption được kiểm tra ở bước tạo snapshot/encoder."
                );
                scenarioRepository.saveAndFlush(savedScenario);
            } catch (RuntimeException exception) {
                savedScenario.setStatus(PlanningScenarioStatus.DRAFT);
                savedScenario.setNote("Không thể khóa tự động: " + exception.getMessage());
                scenarioRepository.saveAndFlush(savedScenario);
            }
            scenarios.add(savedScenario);
        }
        return List.copyOf(scenarios);
    }

    private List<TeachingPart> loadParts(AutomaticScenarioRequest request) {
        if (request.scopeType() == ScenarioScopeType.FULL_TERM) {
            return teachingPartRepository
                    .findByCourseSectionAcademicTermTermCodeAndCourseSectionStatusOrderByPartCode(
                            request.termCode(),
                            CourseSectionStatus.APPROVED
                    );
        }

        List<TeachingPart> parts = teachingPartRepository.findAllById(request.teachingPartIds());
        if (parts.size() != request.teachingPartIds().size()) {
            throw new IllegalArgumentException("Có TeachingPart trong SUBSET không tồn tại.");
        }
        for (TeachingPart part : parts) {
            String partTermCode = part.getCourseSection().getAcademicTerm().getTermCode();
            if (!request.termCode().equals(partTermCode)) {
                throw new IllegalArgumentException(
                        "TeachingPart " + part.getPartCode() + " không thuộc học kỳ yêu cầu.");
            }
            if (part.getCourseSection().getStatus() == CourseSectionStatus.CANCELLED) {
                throw new IllegalArgumentException(
                        "Không thể xếp TeachingPart của lớp học phần đã hủy: "
                                + part.getPartCode() + ".");
            }
        }
        return parts.stream().sorted(Comparator.comparing(TeachingPart::getPartCode)).toList();
    }

    private void validateStructure(
            PlanningScenario scenario,
            List<PlanningScenarioItem> items,
            String termCode,
            int expectedPartCount
    ) {
        if (items.isEmpty()) {
            throw new IllegalStateException("Scenario chưa chọn plan nào.");
        }

        Set<Long> seenPartIds = new HashSet<>();
        for (PlanningScenarioItem item : items) {
            TeachingPart part = item.getTeachingPart();
            TeachingPlan plan = item.getTeachingPlan();
            if (!seenPartIds.add(part.getTeachingPartId())) {
                throw new IllegalStateException("Scenario chọn nhiều plan cho cùng TeachingPart.");
            }
            if (plan.getStatus() != TeachingPlanStatus.VALID) {
                throw new IllegalStateException("Scenario chỉ được chọn TeachingPlan VALID.");
            }
            if (!Objects.equals(plan.getTeachingPart().getTeachingPartId(), part.getTeachingPartId())) {
                throw new IllegalStateException("TeachingPlan không thuộc TeachingPart tương ứng.");
            }

            List<ClassSession> sessions = classSessionRepository
                    .findByTeachingPlanTeachingPlanIdOrderBySessionNumber(plan.getTeachingPlanId());
            if (sessions.isEmpty()) {
                throw new IllegalStateException("Plan " + plan.getPlanCode() + " chưa có ClassSession.");
            }
            int totalPeriods = 0;
            int expectedSessionNumber = 1;
            for (ClassSession session : sessions) {
                if (session.getSessionNumber() != expectedSessionNumber++) {
                    throw new IllegalStateException("Session number của plan không liên tục.");
                }
                String sessionTerm = session.getTermWeek().getAcademicTerm().getTermCode();
                if (!termCode.equals(sessionTerm)) {
                    throw new IllegalStateException("ClassSession không thuộc học kỳ của scenario.");
                }
                totalPeriods += session.getDurationPeriods();
            }
            if (totalPeriods != part.getTotalPeriods()) {
                throw new IllegalStateException(
                        "Plan " + plan.getPlanCode() + " không đủ tổng tiết của TeachingPart."
                );
            }
        }

        if (seenPartIds.size() != expectedPartCount) {
            throw new IllegalStateException(
                    "Scenario không bao phủ đúng toàn bộ TeachingPart trong phạm vi yêu cầu."
            );
        }
    }

    private TeachingPart requirePart(Map<Long, TeachingPart> partsById, long partId) {
        TeachingPart part = partsById.get(partId);
        if (part == null) {
            throw new IllegalStateException("Không tìm thấy TeachingPart " + partId + " trong phạm vi.");
        }
        return part;
    }

    private TeachingPlan requirePlan(Map<Long, TeachingPlan> plansById, long planId) {
        TeachingPlan plan = plansById.get(planId);
        if (plan == null) {
            throw new IllegalStateException("Không tìm thấy TeachingPlan " + planId + ".");
        }
        return plan;
    }

    private String buildBatchCode(String termCode) {
        String normalizedTerm = termCode.toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9]+", "_")
                .replaceAll("^_+|_+$", "");
        if (normalizedTerm.length() > 8) {
            normalizedTerm = normalizedTerm.substring(0, 8);
        }
        String timestamp = java.time.format.DateTimeFormatter.ofPattern("yyyyMMddHHmmss")
                .format(LocalDateTime.now());
        String randomSuffix = UUID.randomUUID().toString()
                .replace("-", "")
                .substring(0, 6)
                .toUpperCase(Locale.ROOT);
        return "AUTO_%s_%s_%s".formatted(normalizedTerm, timestamp, randomSuffix);
    }
}
