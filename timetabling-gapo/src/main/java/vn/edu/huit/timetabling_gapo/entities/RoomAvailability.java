package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.AvailabilityScopeType;
import vn.edu.huit.timetabling_gapo.enums.AvailabilityType;

import java.time.LocalDate;

@Entity
@Table(name = "RoomAvailability")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class RoomAvailability {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "availability_id")
    private Long availabilityId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "room_location_id", nullable = false)
    private Room room;

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

    @Column(name = "note", length = 255)
    private String note;
}
