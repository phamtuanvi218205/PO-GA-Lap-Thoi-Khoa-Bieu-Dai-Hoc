package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "Lecturer")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class Lecturer {
    @Id
    @Column(name = "lecturer_code", length = 20)
    private String lecturerCode;

    @Column(name = "full_name", nullable = false, length = 150)
    private String fullName;

    @Column(name = "email", length = 150)
    private String email;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "home_campus_code")
    private Campus homeCampus;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
