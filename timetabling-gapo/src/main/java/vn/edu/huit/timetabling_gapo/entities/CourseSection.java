package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.CourseSectionStatus;

@Entity
@Table(name = "CourseSection")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class CourseSection {
    @Id
    @Column(name = "section_code", length = 30)
    private String sectionCode;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "course_code", nullable = false)
    private Course course;

    @Column(name = "section_name", length = 150)
    private String sectionName;

    @Column(name = "expected_enrollment")
    private Integer expectedEnrollment;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private CourseSectionStatus status;
}
