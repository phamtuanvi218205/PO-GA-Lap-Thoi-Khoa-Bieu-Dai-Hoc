package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.AllowedPeriodBlockId;

@Entity
@Table(name = "AllowedPeriodBlock")
@IdClass(AllowedPeriodBlockId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class AllowedPeriodBlock {
    @Id
    @Column(name = "start_period")
    private Integer startPeriod;

    @Id
    @Column(name = "duration_periods")
    private Integer durationPeriods;

    @Column(name = "end_period", insertable = false, updatable = false)
    private Integer endPeriod;

    @Column(name = "block_name", length = 100)
    private String blockName;

    @Column(name = "is_active", nullable = false)
    private Boolean active;
}
