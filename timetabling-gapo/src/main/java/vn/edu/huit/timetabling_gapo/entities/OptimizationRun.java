package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.OptimizationAlgorithm;
import vn.edu.huit.timetabling_gapo.enums.OptimizationStatus;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "OptimizationRun")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class OptimizationRun {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "run_id")
    private Long runId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "scenario_id", nullable = false)
    private PlanningScenario planningScenario;

    @Enumerated(EnumType.STRING)
    @Column(name = "algorithm_name", nullable = false, length = 30)
    private OptimizationAlgorithm algorithmName;

    @Column(name = "population_size", nullable = false)
    private Integer populationSize;

    @Column(name = "max_fitness_evaluations", nullable = false)
    private Long maxFitnessEvaluations;

    @Column(name = "random_seed", nullable = false)
    private Long randomSeed;

    @Column(name = "algorithm_version", nullable = false, length = 50)
    private String algorithmVersion;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private OptimizationStatus status;

    @Column(name = "hard_violation_count")
    private Integer hardViolationCount;

    /** Điểm ổn định thứ và tiết bắt đầu; được so sánh trước hai tầng mềm còn lại. */
    @Column(name = "time_stability_score", precision = 18, scale = 6)
    private BigDecimal timeStabilityScore;

    @Column(name = "general_quality_score", precision = 18, scale = 6)
    private BigDecimal generalQualityScore;

    @Column(name = "lecturer_preference_score", precision = 18, scale = 6)
    private BigDecimal lecturerPreferenceScore;

    /**
     * JSON lưu số lần đổi thứ, đổi tiết, đổi phòng, ngoại lệ hợp lệ,
     * các component chất lượng chung và chi tiết preference theo giảng viên.
     */
    @Lob
    @Column(name = "fitness_breakdown_json", columnDefinition = "nvarchar(max)")
    private String fitnessBreakdownJson;

    @Lob
    @Column(name = "snapshot_json", nullable = false, columnDefinition = "nvarchar(max)")
    private String snapshotJson;

    /** SHA-256 của JSON canonical để phát hiện snapshot bị thay đổi. */
    @Column(name = "snapshot_checksum", nullable = false, length = 64)
    private String snapshotChecksum;

    @Lob
    @Column(name = "gene_option_mapping_json", nullable = false, columnDefinition = "nvarchar(max)")
    private String geneOptionMappingJson;

    @Column(name = "started_at")
    private LocalDateTime startedAt;

    @Column(name = "finished_at")
    private LocalDateTime finishedAt;

    @Lob
    @Column(name = "error_message", columnDefinition = "nvarchar(max)")
    private String errorMessage;
}
