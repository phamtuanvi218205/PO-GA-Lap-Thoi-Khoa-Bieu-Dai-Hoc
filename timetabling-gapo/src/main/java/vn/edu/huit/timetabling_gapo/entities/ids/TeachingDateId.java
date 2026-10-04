package vn.edu.huit.timetabling_gapo.entities.ids;

import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;

import java.io.Serializable;
import java.time.LocalDate;

@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class TeachingDateId implements Serializable {
    private String academicTerm;
    private LocalDate calendarDate;
}
