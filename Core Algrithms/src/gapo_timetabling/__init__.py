"""Core domain cho bài toán xếp lịch giảng dạy trước đăng ký.

Các module được tách theo một chuỗi trách nhiệm rõ ràng:

* ``models`` định nghĩa snapshot đầu vào và dữ liệu kết quả bất biến;
* ``encoder`` sinh miền lựa chọn hợp lệ riêng cho từng buổi;
* ``decoder`` ghép vector random-key thành một lịch hoàn chỉnh;
* ``repair`` thử thay đổi tối thiểu khi một lần decode thất bại;
* ``constraints`` kiểm tra độc lập các điều kiện bắt buộc;
* ``fitness`` đánh giá ba tầng chất lượng của lịch đã hợp lệ;
* ``population`` tạo và đánh giá cá thể theo cùng một pipeline dùng chung;
* ``snapshot`` đọc hợp đồng JSON từ Java, kiểm tra checksum và chạy preflight;
* ``metrics`` định nghĩa dữ liệu kết quả và hội tụ dùng chung giữa các optimizer.

Các thuật toán GA, PO và GA–PO sử dụng hợp đồng này nhưng không được đặt
logic cơ sở dữ liệu, API hoặc quy tắc nghiệp vụ mới trực tiếp vào optimizer.
"""
