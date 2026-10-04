package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

import java.math.BigDecimal;

@Entity
@Table(name = "Course")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class Course {
    @Id
    @Column(name = "course_code", length = 20)
    private String courseCode;

    @Column(name = "course_name", nullable = false, length = 200)
    private String courseName;

    @Column(name = "credits", precision = 4, scale = 1)
    private BigDecimal credits;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
