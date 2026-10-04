package vn.edu.huit.timetabling_gapo.entities.ids;

import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;

import java.io.Serializable;

@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class RoomEquipmentId implements Serializable {
    private Long room;
    private String equipment;
}
