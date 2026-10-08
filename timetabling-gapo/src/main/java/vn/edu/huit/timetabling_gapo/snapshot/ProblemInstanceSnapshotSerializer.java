package vn.edu.huit.timetabling_gapo.snapshot;

import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.SerializationFeature;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Serialize snapshot theo một dạng canonical duy nhất để checksum tái lập. */
@Component
public class ProblemInstanceSnapshotSerializer {

    private final ObjectMapper canonicalMapper;

    public ProblemInstanceSnapshotSerializer(ObjectMapper applicationObjectMapper) {
        this.canonicalMapper = applicationObjectMapper.rebuild()
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .enable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
                .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
                .build();
    }

    public BuiltProblemInstanceSnapshot serialize(ProblemInstanceSnapshot snapshot) {
        try {
            String json = canonicalMapper.writeValueAsString(snapshot);
            return new BuiltProblemInstanceSnapshot(snapshot, json, sha256(json));
        } catch (JacksonException exception) {
            throw new IllegalStateException("Không thể serialize ProblemInstance snapshot.", exception);
        }
    }

    /**
     * Đọc lại JSON bằng đúng cấu hình canonical. Phương thức này chủ yếu dùng
     * để kiểm tra round-trip và bảo vệ version trước khi một snapshot lưu trữ
     * được dùng lại ở Java.
     */
    public ProblemInstanceSnapshot deserialize(String json) {
        try {
            ProblemInstanceSnapshot snapshot = canonicalMapper.readValue(
                    json,
                    ProblemInstanceSnapshot.class
            );
            if (!ProblemInstanceSnapshot.SCHEMA_VERSION.equals(snapshot.schemaVersion())) {
                throw new IllegalArgumentException(
                        "Không hỗ trợ snapshot schema version: " + snapshot.schemaVersion()
                );
            }
            return snapshot;
        } catch (JacksonException exception) {
            throw new IllegalArgumentException("Snapshot JSON không hợp lệ.", exception);
        }
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(
                    digest.digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("JVM không hỗ trợ SHA-256.", exception);
        }
    }
}
