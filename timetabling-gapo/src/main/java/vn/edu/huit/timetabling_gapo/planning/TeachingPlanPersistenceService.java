package vn.edu.huit.timetabling_gapo.planning;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.edu.huit.timetabling_gapo.entities.*;
import vn.edu.huit.timetabling_gapo.enums.PlanningScenarioStatus;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;
import vn.edu.huit.timetabling_gapo.repositories.*;

import java.time.LocalDateTime;
import java.util.*;

/**
 * Điều phối luồng production từ dữ liệu rời rạc đến TeachingPlanItem và
 * ClassSession đã được lưu. Service không chọn ngày, tiết hoặc phòng.
 */
@Service
@RequiredArgsConstructor
public class TeachingPlanPersistenceService {

    private final TeachingPartRepository teachingPartRepository;
    private final TeachingPlanGenerationRuleRepository generationRuleRepository;
    private final TeachingDurationRuleRepository durationRuleRepository;
    private final TermWeekRepository termWeekRepository;
    private final TeachingPlanRepository teachingPlanRepository;
    private final TeachingPlanItemRepository teachingPlanItemRepository;
    private final ClassSessionRepository classSessionRepository;
    private final PlanningScenarioItemRepository scenarioItemRepository;
    private final TeachingPlanGenerator planGenerator;
    private final SessionExpander sessionExpander;

    /**
     * Bảo đảm TeachingPart có đúng thế hệ plan hiện hành theo rule đang lưu.
     * Cùng input trả lại plan cũ, không nhân đôi dữ liệu.
     */
    @Transactional
    public List<TeachingPlan> ensureCurrentPlans(Long teachingPartId) {
        TeachingPart part = teachingPartRepository.findById(teachingPartId)
                .orElseThrow(() -> new IllegalArgumentException(
                        "Không tìm thấy TeachingPart " + teachingPartId + "."));

        TeachingPlanGenerationRule rule = generationRuleRepository
                .findByTeachingPartTeachingPartIdAndActiveTrue(teachingPartId)
                .orElseThrow(() -> new IllegalStateException(
                        "TeachingPart " + part.getPartCode() + " chưa có rule sinh plan đang hoạt động."));

        List<Integer> allowedDurations = durationRuleRepository
                .findByPartTypeOrderByDurationPeriods(part.getPartType())
                .stream()
                .map(TeachingDurationRule::getDurationPeriods)
                .distinct()
                .sorted()
                .toList();
        if (allowedDurations.isEmpty()) {
            throw new IllegalStateException(
                    "Loại phần " + part.getPartType() + " chưa có TeachingDurationRule.");
        }

        String termCode = part.getCourseSection().getAcademicTerm().getTermCode();
        Map<Integer, TermWeek> weeksByNumber = loadAndValidateWeeks(termCode, rule);
        String generationKey = PlanGenerationKeyFactory.create(part, rule, allowedDurations);

        List<TeachingPlan> existingPlans = teachingPlanRepository
                .findByTeachingPartTeachingPartIdAndGenerationKeyOrderByCandidateRank(
                        teachingPartId,
                        generationKey
                );
        if (!existingPlans.isEmpty()) {
            validatePersistedGeneration(existingPlans, part);
            existingPlans.forEach(plan -> plan.setStatus(TeachingPlanStatus.VALID));
            teachingPlanRepository.saveAll(existingPlans);
            retireSupersededPlans(teachingPartId, generationKey);
            return List.copyOf(existingPlans);
        }

        TeachingPlanGenerationRequest request = new TeachingPlanGenerationRequest(
                part.getPartCode(),
                part.getTotalPeriods(),
                rule.getStartWeekNumber(),
                rule.getEndWeekNumber(),
                allowedDurations,
                rule.getMaxSessionsPerWeek(),
                rule.getAllowsIntensive(),
                rule.getMaxCandidatePlans()
        );
        List<GeneratedTeachingPlan> generatedPlans = planGenerator.generate(request);
        if (generatedPlans.isEmpty()) {
            throw new IllegalStateException(
                    "Không thể sinh TeachingPlan đủ " + part.getTotalPeriods()
                            + " tiết cho " + part.getPartCode() + ".");
        }

        int generationNo = teachingPlanRepository.findMaximumGenerationNo(teachingPartId) + 1;
        List<TeachingPlan> persistedPlans = new ArrayList<>(generatedPlans.size());
        for (GeneratedTeachingPlan generatedPlan : generatedPlans) {
            TeachingPlan plan = persistPlan(
                    part,
                    generatedPlan,
                    generationNo,
                    generationKey,
                    weeksByNumber
            );
            persistedPlans.add(plan);
        }

        retireSupersededPlans(teachingPartId, generationKey);
        return List.copyOf(persistedPlans);
    }

    /**
     * Không tái sử dụng một generation chỉ vì checksum trùng nếu dữ liệu con
     * của generation đó đã bị thiếu hoặc hỏng. Một plan hợp lệ phải có cùng
     * số item/session, thứ tự liên tục và tổng duration đúng bằng tổng tiết
     * của TeachingPart.
     */
    private void validatePersistedGeneration(
            List<TeachingPlan> plans,
            TeachingPart part
    ) {
        int expectedCandidateRank = 1;
        for (TeachingPlan plan : plans) {
            if (plan.getCandidateRank() != expectedCandidateRank++) {
                throw new IllegalStateException(
                        "Generation hiện có của " + part.getPartCode()
                                + " có candidate rank không liên tục."
                );
            }

            List<TeachingPlanItem> items = teachingPlanItemRepository
                    .findByTeachingPlanTeachingPlanIdOrderByItemNumber(plan.getTeachingPlanId());
            List<ClassSession> sessions = classSessionRepository
                    .findByTeachingPlanTeachingPlanIdOrderBySessionNumber(plan.getTeachingPlanId());
            if (items.isEmpty() || items.size() != sessions.size()) {
                throw new IllegalStateException(
                        "Plan " + plan.getPlanCode()
                                + " thiếu TeachingPlanItem hoặc ClassSession."
                );
            }

            int totalItemPeriods = 0;
            int totalSessionPeriods = 0;
            for (int index = 0; index < items.size(); index++) {
                int expectedNumber = index + 1;
                TeachingPlanItem item = items.get(index);
                ClassSession session = sessions.get(index);
                if (item.getItemNumber() != expectedNumber
                        || session.getSessionNumber() != expectedNumber) {
                    throw new IllegalStateException(
                            "Plan " + plan.getPlanCode() + " có thứ tự item/session không liên tục."
                    );
                }
                if (!sameTermWeek(item.getTermWeek(), session.getTermWeek())
                        || item.getDurationPeriods() != session.getDurationPeriods()
                        || item.getStabilityGroupNo() != session.getStabilityGroupNo()) {
                    throw new IllegalStateException(
                            "Plan " + plan.getPlanCode()
                                    + " có TeachingPlanItem và ClassSession không đồng nhất."
                    );
                }
                totalItemPeriods += item.getDurationPeriods();
                totalSessionPeriods += session.getDurationPeriods();
            }
            if (totalItemPeriods != part.getTotalPeriods()
                    || totalSessionPeriods != part.getTotalPeriods()) {
                throw new IllegalStateException(
                        "Plan " + plan.getPlanCode() + " không đủ tổng tiết của TeachingPart."
                );
            }
        }
    }

    private boolean sameTermWeek(TermWeek left, TermWeek right) {
        return Objects.equals(left.getWeekNumber(), right.getWeekNumber())
                && Objects.equals(
                left.getAcademicTerm().getTermCode(),
                right.getAcademicTerm().getTermCode()
        );
    }

    private Map<Integer, TermWeek> loadAndValidateWeeks(
            String termCode,
            TeachingPlanGenerationRule rule
    ) {
        Map<Integer, TermWeek> weeksByNumber = new HashMap<>();
        for (TermWeek week : termWeekRepository.findByAcademicTermTermCodeOrderByWeekNumber(termCode)) {
            weeksByNumber.put(week.getWeekNumber(), week);
        }
        for (int weekNumber = rule.getStartWeekNumber();
             weekNumber <= rule.getEndWeekNumber();
             weekNumber++) {
            if (!weeksByNumber.containsKey(weekNumber)) {
                throw new IllegalStateException(
                        "Học kỳ " + termCode + " thiếu TermWeek " + weekNumber + ".");
            }
        }
        return weeksByNumber;
    }

    private TeachingPlan persistPlan(
            TeachingPart part,
            GeneratedTeachingPlan generatedPlan,
            int generationNo,
            String generationKey,
            Map<Integer, TermWeek> weeksByNumber
    ) {
        TeachingPlan plan = new TeachingPlan();
        plan.setTeachingPart(part);
        plan.setPlanCode(buildPersistentPlanCode(
                part.getPartCode(),
                generationNo,
                generatedPlan.sequenceNumber()
        ));
        plan.setPlanName(generatedPlan.planName());
        plan.setStatus(generatedPlan.status());
        plan.setAllowsIntensive(generatedPlan.intensive());
        plan.setGenerationNo(generationNo);
        plan.setCandidateRank(generatedPlan.sequenceNumber());
        plan.setGenerationKey(generationKey);
        plan.setGeneratedAt(LocalDateTime.now());
        plan.setNote("Kế hoạch được hệ thống sinh tự động từ generation key " + generationKey + ".");
        TeachingPlan savedPlan = teachingPlanRepository.save(plan);

        List<TeachingPlanItem> items = generatedPlan.items().stream()
                .map(item -> {
                    TeachingPlanItem entity = new TeachingPlanItem();
                    entity.setTeachingPlan(savedPlan);
                    entity.setItemNumber(item.itemNumber());
                    entity.setTermWeek(requireWeek(weeksByNumber, item.weekNumber()));
                    entity.setSessionOrderInWeek(item.sessionOrderInWeek());
                    entity.setDurationPeriods(item.durationPeriods());
                    entity.setStabilityGroupNo(item.stabilityGroupNo());
                    return entity;
                })
                .toList();
        teachingPlanItemRepository.saveAll(items);

        List<ExpandedClassSession> expandedSessions = sessionExpander.expand(
                generatedPlan,
                part.getRequiredLocationType()
        );
        List<ClassSession> sessions = expandedSessions.stream()
                .map(expanded -> {
                    ClassSession session = new ClassSession();
                    session.setTeachingPlan(savedPlan);
                    session.setSessionNumber(expanded.sessionNumber());
                    session.setStabilityGroupNo(expanded.stabilityGroupNo());
                    session.setTermWeek(requireWeek(weeksByNumber, expanded.weekNumber()));
                    session.setDurationPeriods(expanded.durationPeriods());
                    session.setRequiredLocationType(expanded.requiredLocationType());
                    return session;
                })
                .toList();
        classSessionRepository.saveAll(sessions);
        return savedPlan;
    }

    private TermWeek requireWeek(Map<Integer, TermWeek> weeksByNumber, int weekNumber) {
        TermWeek week = weeksByNumber.get(weekNumber);
        if (week == null) {
            throw new IllegalStateException("Plan sinh ra tuần không tồn tại: " + weekNumber + ".");
        }
        return week;
    }

    private void retireSupersededPlans(Long teachingPartId, String currentGenerationKey) {
        List<TeachingPlan> validPlans = teachingPlanRepository
                .findByTeachingPartTeachingPartIdAndStatusOrderByCandidateRank(
                        teachingPartId,
                        TeachingPlanStatus.VALID
                );
        for (TeachingPlan plan : validPlans) {
            if (currentGenerationKey.equals(plan.getGenerationKey())) {
                continue;
            }

            boolean usedByLockedScenario = scenarioItemRepository
                    .existsByTeachingPlanTeachingPlanIdAndPlanningScenarioStatus(
                            plan.getTeachingPlanId(),
                            PlanningScenarioStatus.LOCKED
                    );
            if (!usedByLockedScenario) {
                plan.setStatus(TeachingPlanStatus.RETIRED);
                teachingPlanRepository.save(plan);
            }
        }
    }

    private String buildPersistentPlanCode(String partCode, int generationNo, int candidateRank) {
        String suffix = "_G%03d_P%02d".formatted(generationNo, candidateRank);
        String base = partCode.trim()
                .toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9]+", "_")
                .replaceAll("^_+|_+$", "");
        int maximumBaseLength = 40 - suffix.length();
        if (base.length() > maximumBaseLength) {
            base = base.substring(0, maximumBaseLength);
        }
        return base + suffix;
    }
}
