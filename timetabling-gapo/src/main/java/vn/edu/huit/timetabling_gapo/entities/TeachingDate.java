package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingDateId;
import vn.edu.huit.timetabling_gapo.enums.DateStatus;

import java.time.LocalDate;

@Entity
@Table(name = "TeachingDate")
@IdClass(TeachingDateId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingDate {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Id
    @Column(name = "calendar_date")
    private LocalDate calendarDate;

    @Column(name = "week_number", nullable = false)
    private Integer weekNumber;

    @Column(name = "iso_weekday", nullable = false)
    private Integer isoWeekday;

    @Enumerated(EnumType.STRING)
    @Column(name = "date_status", nullable = false, length = 20)
    private DateStatus dateStatus;

    @Column(name = "note", length = 255)
    private String note;
}
