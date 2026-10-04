package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingDurationRuleId;
import vn.edu.huit.timetabling_gapo.enums.PartType;

@Entity
@Table(name = "TeachingDurationRule")
@IdClass(TeachingDurationRuleId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TeachingDurationRule {
    @Id
    @Enumerated(EnumType.STRING)
    @Column(name = "part_type", length = 20)
    private PartType partType;

    @Id
    @Column(name = "duration_periods")
    private Integer durationPeriods;

    @Column(name = "is_standard", nullable = false)
    private Boolean standard;

    @Column(name = "note", length = 255)
    private String note;
}
