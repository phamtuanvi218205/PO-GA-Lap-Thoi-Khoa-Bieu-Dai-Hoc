package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "Campus")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class Campus {
    @Id
    @Column(name = "campus_code", length = 20)
    private String campusCode;

    @Column(name = "campus_name", nullable = false, length = 150)
    private String campusName;

    @Column(name = "address", length = 255)
    private String address;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
