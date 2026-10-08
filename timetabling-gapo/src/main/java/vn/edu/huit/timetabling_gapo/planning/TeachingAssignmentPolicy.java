package vn.edu.huit.timetabling_gapo.planning;

import vn.edu.huit.timetabling_gapo.entities.TeachingPart;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

/**
 * Kiểm tra các bất biến của phân công giảng viên trước khi tạo đề bài tối ưu.
 *
 * <p>Mỗi {@code TeachingPart} vẫn lưu giảng viên để việc tạo snapshot và tra
 * cứu lịch được trực tiếp. Tuy nhiên, mọi phần lý thuyết/thực hành thuộc cùng
 * một lớp học phần phải tham chiếu cùng một giảng viên đã phân công. Đây là
 * quy tắc dữ liệu đầu vào; GA và PO không được chọn hoặc đổi người dạy.</p>
 */
public final class TeachingAssignmentPolicy {

    private TeachingAssignmentPolicy() {
        // Lớp tiện ích chỉ cung cấp phép kiểm tra tĩnh.
    }

    /**
     * Từ chối tập phần giảng dạy nếu một lớp học phần có nhiều giảng viên.
     *
     * @param parts các phần giảng dạy nằm trong cùng phạm vi chuẩn bị lịch
     * @throws IllegalStateException khi dữ liệu thiếu liên kết bắt buộc hoặc
     *                               cùng lớp học phần dùng giảng viên khác nhau
     */
    public static void requireOneLecturerPerCourseSection(
            Collection<TeachingPart> parts
    ) {
        Map<String, String> lecturerCodeBySection = new HashMap<>();

        for (TeachingPart part : parts) {
            if (part.getCourseSection() == null) {
                throw new IllegalStateException(
                        "TeachingPart " + part.getPartCode() + " chưa có CourseSection."
                );
            }
            if (part.getLecturer() == null) {
                throw new IllegalStateException(
                        "TeachingPart " + part.getPartCode() + " chưa có giảng viên."
                );
            }

            String sectionCode = part.getCourseSection().getSectionCode();
            String lecturerCode = part.getLecturer().getLecturerCode();
            String assignedLecturerCode = lecturerCodeBySection.putIfAbsent(
                    sectionCode,
                    lecturerCode
            );

            if (assignedLecturerCode != null
                    && !assignedLecturerCode.equals(lecturerCode)) {
                throw new IllegalStateException(
                        "Mọi TeachingPart thuộc CourseSection " + sectionCode
                                + " phải dùng chung một giảng viên."
                );
            }
        }
    }
}
