package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.entities.TeachingPart;
import vn.edu.huit.timetabling_gapo.entities.TeachingPlanGenerationRule;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;

/** Tạo khóa SHA-256 xác định cho toàn bộ dữ liệu ảnh hưởng đến việc sinh plan. */
final class PlanGenerationKeyFactory {

    private PlanGenerationKeyFactory() {
    }

    static String create(
            TeachingPart part,
            TeachingPlanGenerationRule rule,
            List<Integer> allowedDurations
    ) {
        String termCode = part.getCourseSection().getAcademicTerm().getTermCode();
        String canonicalValue = String.join("|",
                termCode,
                part.getPartCode(),
                part.getPartType().name(),
                String.valueOf(part.getTotalPeriods()),
                part.getRequiredLocationType().name(),
                String.valueOf(rule.getStartWeekNumber()),
                String.valueOf(rule.getEndWeekNumber()),
                String.valueOf(rule.getMaxSessionsPerWeek()),
                String.valueOf(rule.getAllowsIntensive()),
                String.valueOf(rule.getMaxCandidatePlans()),
                allowedDurations.stream().sorted().map(String::valueOf).reduce((a, b) -> a + "," + b).orElse("")
        );

        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().withUpperCase()
                    .formatHex(digest.digest(canonicalValue.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("JVM không hỗ trợ SHA-256.", exception);
        }
    }
}
