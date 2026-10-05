package vn.edu.huit.timetabling_gapo.planning;

/** Một plan có thể được chọn cho một TeachingPart khi tạo scenario tự động. */
public record ScenarioPlanCandidate(
        long teachingPartId,
        long teachingPlanId,
        int candidateRank,
        boolean intensive
) {
    public ScenarioPlanCandidate {
        if (teachingPartId <= 0 || teachingPlanId <= 0 || candidateRank <= 0) {
            throw new IllegalArgumentException("Định danh và thứ hạng plan phải lớn hơn 0.");
        }
    }
}
