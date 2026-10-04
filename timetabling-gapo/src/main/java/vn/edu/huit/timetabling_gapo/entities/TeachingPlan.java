package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;

import java.time.LocalDateTime;

@Entity
@Table(name = "TeachingPlan")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingPlan {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "teaching_plan_id")
    private Long teachingPlanId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_part_id", nullable = false)
    private TeachingPart teachingPart;

    @Column(name = "plan_code", nullable = false, unique = true, length = 40)
    private String planCode;

    @Column(name = "plan_name", nullable = false, length = 180)
    private String planName;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private TeachingPlanStatus status;

    @Column(name = "allows_intensive", nullable = false)
    private Boolean allowsIntensive;

    @Column(name = "approved_by", length = 150)
    private String approvedBy;

    @Column(name = "approved_at")
    private LocalDateTime approvedAt;

    @Column(name = "note", length = 500)
    private String note;
}
