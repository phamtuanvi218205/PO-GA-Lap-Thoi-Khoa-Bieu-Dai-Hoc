package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.AcademicTermStatus;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "AcademicTerm")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class AcademicTerm {
    @Id
    @Column(name = "term_code", length = 20)
    private String termCode;

    @Column(name = "term_name", nullable = false, length = 150)
    private String termName;

    @Column(name = "start_date", nullable = false)
    private LocalDate startDate;

    @Column(name = "end_date", nullable = false)
    private LocalDate endDate;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private AcademicTermStatus status;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
}
