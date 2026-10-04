package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.RoomType;

@Entity
@Table(name = "Room")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class Room {
    @Id
    @Column(name = "location_id")
    private Long locationId;

    @MapsId
    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "location_id", nullable = false)
    private TeachingLocation teachingLocation;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "campus_code", nullable = false)
    private Campus campus;

    @Enumerated(EnumType.STRING)
    @Column(name = "room_type", nullable = false, length = 30)
    private RoomType roomType;

    @Column(name = "capacity")
    private Integer capacity;
}
