package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.PlanningScenarioStatus;
import vn.edu.huit.timetabling_gapo.enums.ScenarioScopeType;

import java.time.LocalDateTime;

@Entity
@Table(name = "PlanningScenario")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class PlanningScenario {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "scenario_id")
    private Long scenarioId;

    @Column(name = "scenario_code", nullable = false, unique = true, length = 40)
    private String scenarioCode;

    @Column(name = "scenario_name", nullable = false, length = 180)
    private String scenarioName;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Enumerated(EnumType.STRING)
    @Column(name = "scope_type", nullable = false, length = 20)
    private ScenarioScopeType scopeType;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private PlanningScenarioStatus status;

    @Column(name = "created_by", nullable = false, length = 150)
    private String createdBy;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "locked_by", length = 150)
    private String lockedBy;

    @Column(name = "locked_at")
    private LocalDateTime lockedAt;

    @Column(name = "note", length = 500)
    private String note;
}
