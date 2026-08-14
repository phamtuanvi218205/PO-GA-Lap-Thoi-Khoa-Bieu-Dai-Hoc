package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import vn.edu.huit.timetabling_gapo.enums.RoomType;

@Entity
@Table(
        name = "TeachingEvent",
        uniqueConstraints = @UniqueConstraint(
                name = "UQ_TeachingEvent_Section_Number",
                columnNames = {"section_code", "event_number"}
        )
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class TeachingEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "event_id")
    private Integer eventId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "section_code", nullable = false)
    private CourseSection courseSection;

    @Column(name = "event_number", nullable = false)
    private Integer eventNumber;

    @Column(name = "duration_periods", nullable = false)
    private Integer durationPeriods;

    @Enumerated(EnumType.STRING)
    @Column(name = "required_room_type", nullable = false, length = 30)
    private RoomType requiredRoomType;
}
