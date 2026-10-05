package vn.edu.huit.timetabling_gapo.planning;

import org.springframework.stereotype.Component;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Sinh tự động các phương án chia tổng số tiết thành các buổi theo rule.
 *
 * <p>Generator không dùng dữ liệu ngày, tiết hoặc phòng. Nó chỉ quyết định
 * tuần và thời lượng của từng buổi. Encoder sẽ xử lý ngày–tiết–địa điểm sau
 * khi plan được mở rộng thành ClassSession.</p>
 *
 * <p>Mỗi tổ hợp số lượng duration tạo một lịch trải đều. Khi rule cho phép
 * học tập trung, generator tạo thêm lịch xếp sớm liên tiếp. Mọi kết quả được
 * loại trùng, sắp thứ tự xác định và giới hạn bởi maxCandidatePlans.</p>
 */
@Component
public class TeachingPlanGenerator {

    public List<GeneratedTeachingPlan> generate(TeachingPlanGenerationRequest request) {
        Objects.requireNonNull(request, "Yêu cầu sinh plan không được null.");

        List<List<Integer>> durationCombinations = new ArrayList<>();
        enumerateDurationCombinations(
                request.allowedDurations(),
                0,
                request.totalPeriods(),
                new int[request.allowedDurations().size()],
                durationCombinations
        );

        int availableSlotCount = request.weekCount() * request.maxSessionsPerWeek();
        Map<String, CandidatePlan> uniqueCandidates = new LinkedHashMap<>();

        for (List<Integer> durations : durationCombinations) {
            if (durations.isEmpty() || durations.size() > availableSlotCount) {
                continue;
            }

            List<Integer> spreadSlots = evenlySpacedSlots(
                    durations.size(),
                    request.weekCount(),
                    request.maxSessionsPerWeek()
            );
            addCandidate(uniqueCandidates, buildCandidate(request, durations, spreadSlots));

            if (request.allowsIntensive()) {
                List<Integer> compactSlots = new ArrayList<>(durations.size());
                for (int slot = 0; slot < durations.size(); slot++) {
                    compactSlots.add(slot);
                }
                addCandidate(uniqueCandidates, buildCandidate(request, durations, compactSlots));
            }
        }

        List<CandidatePlan> sortedCandidates = uniqueCandidates.values().stream()
                .sorted(Comparator
                        .comparing(CandidatePlan::intensive)
                        .thenComparing((CandidatePlan plan) -> plan.items().size(), Comparator.reverseOrder())
                        .thenComparing(CandidatePlan::signature))
                .limit(request.maxCandidatePlans())
                .toList();

        List<GeneratedTeachingPlan> result = new ArrayList<>(sortedCandidates.size());
        for (int index = 0; index < sortedCandidates.size(); index++) {
            CandidatePlan candidate = sortedCandidates.get(index);
            int sequenceNumber = index + 1;
            result.add(new GeneratedTeachingPlan(
                    sequenceNumber,
                    buildPlanCode(request.partCode(), sequenceNumber),
                    buildPlanName(candidate),
                    candidate.intensive(),
                    candidate.items()
            ));
        }
        return List.copyOf(result);
    }

    private void enumerateDurationCombinations(
            List<Integer> allowedDurations,
            int durationIndex,
            int remainingPeriods,
            int[] counts,
            List<List<Integer>> output
    ) {
        int duration = allowedDurations.get(durationIndex);

        if (durationIndex == allowedDurations.size() - 1) {
            if (remainingPeriods % duration != 0) {
                return;
            }
            counts[durationIndex] = remainingPeriods / duration;
            output.add(expandDurationCounts(allowedDurations, counts));
            counts[durationIndex] = 0;
            return;
        }

        int maximumCount = remainingPeriods / duration;
        for (int count = maximumCount; count >= 0; count--) {
            counts[durationIndex] = count;
            enumerateDurationCombinations(
                    allowedDurations,
                    durationIndex + 1,
                    remainingPeriods - count * duration,
                    counts,
                    output
            );
        }
        counts[durationIndex] = 0;
    }

    private List<Integer> expandDurationCounts(List<Integer> durations, int[] counts) {
        List<Integer> result = new ArrayList<>();
        for (int index = 0; index < durations.size(); index++) {
            for (int count = 0; count < counts[index]; count++) {
                result.add(durations.get(index));
            }
        }
        return List.copyOf(result);
    }

    private List<Integer> evenlySpacedSlots(
            int sessionCount,
            int weekCount,
            int maxSessionsPerWeek
    ) {
        if (sessionCount == 1) {
            return List.of(0);
        }

        if (sessionCount <= weekCount) {
            List<Integer> slots = new ArrayList<>(sessionCount);
            for (int index = 0; index < sessionCount; index++) {
                double weekPosition = (double) index * (weekCount - 1) / (sessionCount - 1);
                int weekOffset = (int) Math.round(weekPosition);
                slots.add(weekOffset * maxSessionsPerWeek);
            }
            return List.copyOf(slots);
        }

        int availableSlotCount = weekCount * maxSessionsPerWeek;
        List<Integer> slots = new ArrayList<>(sessionCount);
        for (int index = 0; index < sessionCount; index++) {
            double position = (double) index * (availableSlotCount - 1) / (sessionCount - 1);
            slots.add((int) Math.round(position));
        }
        return List.copyOf(slots);
    }

    private CandidatePlan buildCandidate(
            TeachingPlanGenerationRequest request,
            List<Integer> durations,
            List<Integer> selectedSlots
    ) {
        List<GeneratedTeachingPlanItem> items = new ArrayList<>(durations.size());
        for (int index = 0; index < durations.size(); index++) {
            int slot = selectedSlots.get(index);
            int weekOffset = slot / request.maxSessionsPerWeek();
            int sessionOrderInWeek = slot % request.maxSessionsPerWeek() + 1;

            items.add(new GeneratedTeachingPlanItem(
                    index + 1,
                    request.startWeekNumber() + weekOffset,
                    sessionOrderInWeek,
                    durations.get(index),
                    sessionOrderInWeek
            ));
        }

        int lastWeek = items.get(items.size() - 1).weekNumber();
        boolean intensive = lastWeek < request.endWeekNumber();
        return new CandidatePlan(intensive, List.copyOf(items), buildSignature(items));
    }

    private void addCandidate(Map<String, CandidatePlan> uniqueCandidates, CandidatePlan candidate) {
        uniqueCandidates.putIfAbsent(candidate.signature(), candidate);
    }

    private String buildSignature(List<GeneratedTeachingPlanItem> items) {
        return items.stream()
                .map(item -> item.weekNumber()
                        + ":" + item.sessionOrderInWeek()
                        + ":" + item.durationPeriods())
                .collect(Collectors.joining("|"));
    }

    private String buildPlanCode(String partCode, int sequenceNumber) {
        String normalizedPartCode = partCode.trim()
                .toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9]+", "_")
                .replaceAll("^_+|_+$", "");
        return "%s_AUTO_%02d".formatted(normalizedPartCode, sequenceNumber);
    }

    private String buildPlanName(CandidatePlan candidate) {
        Map<Integer, Long> durationCounts = candidate.items().stream()
                .collect(Collectors.groupingBy(
                        GeneratedTeachingPlanItem::durationPeriods,
                        TreeMap::new,
                        Collectors.counting()
                ));

        String composition = durationCounts.entrySet().stream()
                .map(entry -> entry.getValue() + " buổi x " + entry.getKey() + " tiết")
                .collect(Collectors.joining(" + "));

        return "Tự động: " + composition
                + (candidate.intensive() ? " (tập trung)" : " (trải đều)");
    }

    private record CandidatePlan(
            boolean intensive,
            List<GeneratedTeachingPlanItem> items,
            String signature
    ) {
    }
}
