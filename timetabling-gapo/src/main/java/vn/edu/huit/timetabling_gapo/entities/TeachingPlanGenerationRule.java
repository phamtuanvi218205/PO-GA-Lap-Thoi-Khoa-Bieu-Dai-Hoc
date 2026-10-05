package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

/**
 * Dữ liệu điều khiển việc tự động sinh các phương án chia buổi cho một phần
 * giảng dạy. Tập thời lượng hợp lệ không lưu lặp tại đây mà được lấy từ
 * {@link TeachingDurationRule} theo loại của {@link TeachingPart}.
 */
@Entity
@Table(
        name = "TeachingPlanGenerationRule",
        uniqueConstraints = @UniqueConstraint(
                name = "UQ_TeachingPlanGenerationRule_Part",
                columnNames = "teaching_part_id"
        )
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingPlanGenerationRule {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "generation_rule_id")
    private Long generationRuleId;

    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_part_id", nullable = false)
    private TeachingPart teachingPart;

    @Column(name = "start_week_number", nullable = false)
    private Integer startWeekNumber;

    @Column(name = "end_week_number", nullable = false)
    private Integer endWeekNumber;

    @Column(name = "max_sessions_per_week", nullable = false)
    private Integer maxSessionsPerWeek;

    @Column(name = "allows_intensive", nullable = false)
    private Boolean allowsIntensive;

    @Column(name = "max_candidate_plans", nullable = false)
    private Integer maxCandidatePlans;

    @Column(name = "is_active", nullable = false)
    private Boolean active;

    @Column(name = "note", length = 500)
    private String note;
}
