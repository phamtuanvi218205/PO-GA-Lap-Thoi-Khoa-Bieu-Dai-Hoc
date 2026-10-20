package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.LecturerCourseCapabilityId;

import java.math.BigDecimal;

/** Khả năng và mức phù hợp của một giảng viên đối với một môn học. */
@Entity
@Table(name = "LecturerCourseCapability")
@IdClass(LecturerCourseCapabilityId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class LecturerCourseCapability {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "lecturer_code", nullable = false)
    private Lecturer lecturer;

    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "course_code", nullable = false)
    private Course course;

    @Column(name = "can_teach_lecture", nullable = false)
    private Boolean canTeachLecture;

    @Column(name = "can_teach_practice", nullable = false)
    private Boolean canTeachPractice;

    @Column(name = "suitability_score", nullable = false, precision = 5, scale = 4)
    private BigDecimal suitabilityScore;
}
