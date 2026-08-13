package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.Lob;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import vn.edu.huit.timetabling_gapo.enums.OptimizationAlgorithm;
import vn.edu.huit.timetabling_gapo.enums.OptimizationStatus;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "OptimizationRun")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class OptimizationRun {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "run_id")
    private Long runId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Enumerated(EnumType.STRING)
    @Column(name = "algorithm", nullable = false, length = 20)
    private OptimizationAlgorithm algorithm;

    @Column(name = "population_size")
    private Integer populationSize;

    @Column(name = "max_iterations")
    private Integer maxIterations;

    @Column(name = "ga_population_ratio", precision = 5, scale = 4)
    private BigDecimal gaPopulationRatio;

    @Column(name = "random_seed")
    private Long randomSeed;

    @Column(name = "best_fitness")
    private Double bestFitness;

    @Column(name = "hard_violation_count")
    private Integer hardViolationCount;

    @Column(name = "soft_penalty")
    private Double softPenalty;

    @Column(name = "execution_time_ms")
    private Long executionTimeMs;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private OptimizationStatus status;

    @Lob
    @Column(name = "algorithm_parameters", columnDefinition = "nvarchar(max)")
    private String algorithmParameters;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;
}
