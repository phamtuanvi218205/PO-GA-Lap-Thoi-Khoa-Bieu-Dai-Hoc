package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "Equipment")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class Equipment {
    @Id
    @Column(name = "equipment_code", length = 30)
    private String equipmentCode;

    @Column(name = "equipment_name", nullable = false, length = 150)
    private String equipmentName;
}
