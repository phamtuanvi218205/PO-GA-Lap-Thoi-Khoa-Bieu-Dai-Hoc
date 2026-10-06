package vn.edu.huit.timetabling_gapo.snapshot;

/** Kết quả build gồm object bất biến, JSON canonical và checksum SHA-256. */
public record BuiltProblemInstanceSnapshot(
        ProblemInstanceSnapshot snapshot,
        String canonicalJson,
        String sha256Checksum
) {
}
