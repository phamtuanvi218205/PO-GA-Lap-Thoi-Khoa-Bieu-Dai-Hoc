package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "StudentGroup")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class StudentGroup {

    @Id
    @Column(name = "group_code", length = 20)
    private String groupCode;

    @Column(name = "group_name", nullable = false, length = 100)
    private String groupName;

    @Column(name = "program_name", nullable = false, length = 100)
    private String programName;

    @Column(name = "cohort_year", nullable = false)
    private Integer cohortYear;

    @Column(name = "group_size", nullable = false)
    private Integer groupSize;
}
