package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.TermWeekId;

import java.time.LocalDate;

@Entity
@Table(name = "TermWeek")
@IdClass(TermWeekId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TermWeek {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Id
    @Column(name = "week_number")
    private Integer weekNumber;

    @Column(name = "start_date", nullable = false)
    private LocalDate startDate;

    @Column(name = "end_date", nullable = false)
    private LocalDate endDate;
}
