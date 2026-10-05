package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

/**
 * Một buổi dự kiến thuộc phương án được hệ thống sinh tự động. Các dòng này
 * mô tả đầy đủ tuần và thời lượng của plan trước khi được mở rộng thành
 * {@link ClassSession} cho bộ tối ưu.
 */
@Entity
@Table(
        name = "TeachingPlanItem",
        uniqueConstraints = {
                @UniqueConstraint(
                        name = "UQ_TeachingPlanItem_Plan_Number",
                        columnNames = {"teaching_plan_id", "item_number"}
                ),
                @UniqueConstraint(
                        name = "UQ_TeachingPlanItem_Plan_Week_Order",
                        columnNames = {"teaching_plan_id", "week_number", "session_order_in_week"}
                )
        }
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingPlanItem {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "teaching_plan_item_id")
    private Long teachingPlanItemId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_plan_id", nullable = false)
    private TeachingPlan teachingPlan;

    @Column(name = "item_number", nullable = false)
    private Integer itemNumber;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumns({
            @JoinColumn(name = "term_code", referencedColumnName = "term_code", nullable = false),
            @JoinColumn(name = "week_number", referencedColumnName = "week_number", nullable = false)
    })
    private TermWeek termWeek;

    @Column(name = "session_order_in_week", nullable = false)
    private Integer sessionOrderInWeek;

    @Column(name = "duration_periods", nullable = false)
    private Integer durationPeriods;

    @Column(name = "stability_group_no", nullable = false)
    private Integer stabilityGroupNo;
}
