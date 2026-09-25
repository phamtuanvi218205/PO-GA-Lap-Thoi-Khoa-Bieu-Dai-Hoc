package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingPartRequiredEquipmentId;

@Entity
@Table(name = "TeachingPartRequiredEquipment")
@IdClass(TeachingPartRequiredEquipmentId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingPartRequiredEquipment {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_part_id", nullable = false)
    private TeachingPart teachingPart;

    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "equipment_code", nullable = false)
    private Equipment equipment;

    @Column(name = "minimum_quantity", nullable = false)
    private Integer minimumQuantity;
}
