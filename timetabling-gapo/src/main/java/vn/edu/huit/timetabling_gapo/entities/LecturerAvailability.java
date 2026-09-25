package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.AvailabilityScopeType;
import vn.edu.huit.timetabling_gapo.enums.AvailabilityType;

import java.math.BigDecimal;
import java.time.LocalDate;

@Entity
@Table(name = "LecturerAvailability")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class LecturerAvailability {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "availability_id")
    private Long availabilityId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "lecturer_code", nullable = false)
    private Lecturer lecturer;

    @Enumerated(EnumType.STRING)
    @Column(name = "scope_type", nullable = false, length = 20)
    private AvailabilityScopeType scopeType;

    @Column(name = "calendar_date")
    private LocalDate calendarDate;

    @Column(name = "iso_weekday")
    private Integer isoWeekday;

    @Column(name = "start_period", nullable = false)
    private Integer startPeriod;

    @Column(name = "end_period", nullable = false)
    private Integer endPeriod;

    @Enumerated(EnumType.STRING)
    @Column(name = "availability_type", nullable = false, length = 20)
    private AvailabilityType availabilityType;

    @Column(name = "preference_weight", precision = 8, scale = 3)
    private BigDecimal preferenceWeight;

    @Column(name = "note", length = 255)
    private String note;
}
