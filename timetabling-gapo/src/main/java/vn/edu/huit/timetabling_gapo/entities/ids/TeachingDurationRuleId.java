package vn.edu.huit.timetabling_gapo.entities.ids;

import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;
import vn.edu.huit.timetabling_gapo.enums.PartType;

import java.io.Serializable;

@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class TeachingDurationRuleId implements Serializable {
    private PartType partType;
    private Integer durationPeriods;
}
