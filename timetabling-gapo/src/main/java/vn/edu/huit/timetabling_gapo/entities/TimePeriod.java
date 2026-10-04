package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.SessionType;

import java.time.LocalTime;

@Entity
@Table(name = "TimePeriod")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class TimePeriod {
    @Id
    @Column(name = "period_number")
    private Integer periodNumber;

    @Column(name = "start_time", nullable = false)
    private LocalTime startTime;

    @Column(name = "end_time", nullable = false)
    private LocalTime endTime;

    @Enumerated(EnumType.STRING)
    @Column(name = "session_name", nullable = false, length = 20)
    private SessionType sessionName;
}
