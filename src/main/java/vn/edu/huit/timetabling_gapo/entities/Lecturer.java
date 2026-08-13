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
@Table(name = "Lecturer")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class Lecturer {

    @Id
    @Column(name = "lecturer_code", length = 20)
    private String lecturerCode;

    @Column(name = "lecturer_name", nullable = false, length = 100)
    private String lecturerName;

    @Column(name = "academic_title", length = 50)
    private String academicTitle;
}
