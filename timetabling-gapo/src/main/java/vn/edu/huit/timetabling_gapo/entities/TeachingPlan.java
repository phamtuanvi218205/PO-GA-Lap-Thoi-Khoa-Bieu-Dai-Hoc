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

    /** Số thế hệ tăng dần mỗi khi rule đầu vào của TeachingPart thay đổi. */
    @Column(name = "generation_no", nullable = false)
    private Integer generationNo;

    /** Thứ hạng xác định của plan trong cùng một thế hệ, bắt đầu từ 1. */
    @Column(name = "candidate_rank", nullable = false)
    private Integer candidateRank;

    /** SHA-256 của toàn bộ dữ liệu ảnh hưởng đến kết quả sinh plan. */
    @Column(name = "generation_key", nullable = false, length = 64)
    private String generationKey;

    @Column(name = "generated_at", nullable = false)
    private LocalDateTime generatedAt;

    @Column(name = "note", length = 500)
    private String note;
}
