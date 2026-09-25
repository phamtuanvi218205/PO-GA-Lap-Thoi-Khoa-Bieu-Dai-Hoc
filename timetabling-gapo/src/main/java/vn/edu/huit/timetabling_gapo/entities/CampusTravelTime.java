package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.CampusTravelTimeId;

@Entity
@Table(name = "CampusTravelTime")
@IdClass(CampusTravelTimeId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class CampusTravelTime {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "from_campus_code", nullable = false)
    private Campus fromCampus;

    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "to_campus_code", nullable = false)
    private Campus toCampus;

    @Column(name = "travel_minutes", nullable = false)
    private Integer travelMinutes;
}
