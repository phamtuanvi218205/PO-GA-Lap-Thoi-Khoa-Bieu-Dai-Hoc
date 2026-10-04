package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "OnlineLocation")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class OnlineLocation {
    @Id
    @Column(name = "location_id")
    private Long locationId;

    @MapsId
    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "location_id", nullable = false)
    private TeachingLocation teachingLocation;

    @Column(name = "platform_name", nullable = false, length = 100)
    private String platformName;

    @Column(name = "meeting_note", length = 255)
    private String meetingNote;
}
