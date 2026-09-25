"""Core domain cho bài toán xếp lịch giảng dạy trước đăng ký.

Package cung cấp bốn lớp trách nhiệm độc lập:

* ``models`` định nghĩa snapshot đầu vào và dữ liệu kết quả bất biến;
* ``encoder`` sinh miền lựa chọn hợp lệ riêng cho từng buổi;
* ``decoder`` ghép vector random-key thành một lịch hoàn chỉnh;
* ``constraints`` kiểm tra độc lập các điều kiện bắt buộc.

Các thuật toán GA, PO và GA–PO sẽ sử dụng hợp đồng này nhưng không được đặt
logic nghiệp vụ cơ sở dữ liệu hoặc API trực tiếp vào package.
"""
