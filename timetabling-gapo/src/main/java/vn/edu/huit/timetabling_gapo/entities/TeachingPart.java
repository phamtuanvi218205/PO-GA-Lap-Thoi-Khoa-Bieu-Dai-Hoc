package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.LocationType;
import vn.edu.huit.timetabling_gapo.enums.PartType;
import vn.edu.huit.timetabling_gapo.enums.RoomType;

@Entity
@Table(name = "TeachingPart")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingPart {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "teaching_part_id")
    private Long teachingPartId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "section_code", nullable = false)
    private CourseSection courseSection;

    @Column(name = "part_code", nullable = false, unique = true, length = 30)
    private String partCode;

    @Enumerated(EnumType.STRING)
    @Column(name = "part_type", nullable = false, length = 20)
    private PartType partType;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "lecturer_code", nullable = false)
    private Lecturer lecturer;

    @Column(name = "total_periods", nullable = false)
    private Integer totalPeriods;

    @Enumerated(EnumType.STRING)
    @Column(name = "required_room_type", length = 30)
    private RoomType requiredRoomType;

    @Enumerated(EnumType.STRING)
    @Column(name = "required_location_type", nullable = false, length = 20)
    private LocationType requiredLocationType;

    @Column(name = "note", length = 255)
    private String note;
}
