package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "CourseSection")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class CourseSection {

    @Id
    @Column(name = "section_code", length = 20)
    private String sectionCode;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "course_code", nullable = false)
    private Course course;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "lecturer_code", nullable = false)
    private Lecturer lecturer;

    @Column(name = "enrollment", nullable = false)
    private Integer enrollment;

    @Column(name = "duration_periods", nullable = false)
    private Integer durationPeriods;
}
