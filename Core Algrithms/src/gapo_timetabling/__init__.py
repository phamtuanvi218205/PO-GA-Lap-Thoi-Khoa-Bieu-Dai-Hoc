"""Hệ thống xếp thời khóa biểu đại học sử dụng GA, PO và GA–PO.

Mã nguồn được chia thành hai tầng độc lập về trách nhiệm:

* :mod:`gapo_timetabling.core` chứa toàn bộ lõi thuật toán và mô hình miền;
* :mod:`gapo_timetabling.application` chứa kết nối database, quy trình chuẩn bị
  bài toán, CLI, thực nghiệm và lưu kết quả.

Chiều phụ thuộc luôn đi từ ``application`` vào ``core``. Lõi thuật toán không
được phụ thuộc SQL Server, CLI hoặc chi tiết triển khai của ứng dụng.
"""
