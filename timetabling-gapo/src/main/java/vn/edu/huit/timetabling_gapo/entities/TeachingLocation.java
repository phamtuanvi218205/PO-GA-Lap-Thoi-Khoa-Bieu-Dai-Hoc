package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

@Entity
@Table(name = "TeachingLocation")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingLocation {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "location_id")
    private Long locationId;

    @Column(name = "location_code", nullable = false, unique = true, length = 30)
    private String locationCode;

    @Column(name = "location_name", nullable = false, length = 150)
    private String locationName;

    @Enumerated(EnumType.STRING)
    @Column(name = "location_type", nullable = false, length = 20)
    private LocationType locationType;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
