package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

@Entity
@Table(
        name = "ClassSession",
        uniqueConstraints = @UniqueConstraint(
                name = "UQ_ClassSession_Plan_Number",
                columnNames = {"teaching_plan_id", "session_number"}
        )
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class ClassSession {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "class_session_id")
    private Long classSessionId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_plan_id", nullable = false)
    private TeachingPlan teachingPlan;

    @Column(name = "session_number", nullable = false)
    private Integer sessionNumber;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumns({
            @JoinColumn(name = "term_code", referencedColumnName = "term_code", nullable = false),
            @JoinColumn(name = "week_number", referencedColumnName = "week_number", nullable = false)
    })
    private TermWeek termWeek;

    @Column(name = "duration_periods", nullable = false)
    private Integer durationPeriods;

    @Enumerated(EnumType.STRING)
    @Column(name = "required_location_type", nullable = false, length = 20)
    private LocationType requiredLocationType;

    @Column(name = "note", length = 255)
    private String note;
}
