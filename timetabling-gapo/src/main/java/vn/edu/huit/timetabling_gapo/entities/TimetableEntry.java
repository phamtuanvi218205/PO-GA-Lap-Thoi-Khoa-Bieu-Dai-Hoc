package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

import java.time.LocalDate;

@Entity
@Table(
        name = "TimetableEntry",
        uniqueConstraints = @UniqueConstraint(
                name = "UQ_TimetableEntry_Run_Session",
                columnNames = {"run_id", "class_session_id"}
        )
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TimetableEntry {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "timetable_entry_id")
    private Long timetableEntryId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "run_id", nullable = false)
    private OptimizationRun optimizationRun;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "class_session_id", nullable = false)
    private ClassSession classSession;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Column(name = "teaching_date", nullable = false)
    private LocalDate teachingDate;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "location_id", nullable = false)
    private TeachingLocation teachingLocation;

    @Enumerated(EnumType.STRING)
    @Column(name = "location_type", nullable = false, length = 20)
    private LocationType locationType;

    @Column(name = "start_period", nullable = false)
    private Integer startPeriod;

    @Column(name = "end_period", nullable = false)
    private Integer endPeriod;
}
