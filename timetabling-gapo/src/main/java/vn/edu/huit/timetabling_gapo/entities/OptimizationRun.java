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

    @Column(name = "general_quality_score", precision = 18, scale = 6)
    private BigDecimal generalQualityScore;

    @Column(name = "lecturer_preference_score", precision = 18, scale = 6)
    private BigDecimal lecturerPreferenceScore;

    @Lob
    @Column(name = "snapshot_json", nullable = false, columnDefinition = "nvarchar(max)")
    private String snapshotJson;

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
