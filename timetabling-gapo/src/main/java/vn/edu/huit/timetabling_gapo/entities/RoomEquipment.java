package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.RoomEquipmentId;

@Entity
@Table(name = "RoomEquipment")
@IdClass(RoomEquipmentId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class RoomEquipment {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "room_location_id", nullable = false)
    private Room room;

    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "equipment_code", nullable = false)
    private Equipment equipment;

    @Column(name = "quantity", nullable = false)
    private Integer quantity;
}
