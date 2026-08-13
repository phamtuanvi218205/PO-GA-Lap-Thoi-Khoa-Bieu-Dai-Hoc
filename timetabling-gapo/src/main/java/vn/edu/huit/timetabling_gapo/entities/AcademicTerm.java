package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;

@Entity
@Table(name = "AcademicTerm")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class AcademicTerm {

    @Id
    @Column(name = "term_code", length = 20)
    private String termCode;

    @Column(name = "term_name", nullable = false, length = 100)
    private String termName;

    @Column(name = "academic_year", nullable = false, length = 9)
    private String academicYear;

    @Column(name = "semester", nullable = false)
    private Integer semester;

    @Column(name = "start_date", nullable = false)
    private LocalDate startDate;

    @Column(name = "end_date", nullable = false)
    private LocalDate endDate;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
