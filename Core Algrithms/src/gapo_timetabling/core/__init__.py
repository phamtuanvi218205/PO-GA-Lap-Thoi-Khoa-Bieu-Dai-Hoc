"""Lõi tối ưu thời khóa biểu độc lập với cơ sở dữ liệu và giao diện.

Package này chứa mô hình miền, encoder, decoder, validator, fitness và ba
optimizer GA, PO, GA–PO. Mọi thành phần tại đây chỉ làm việc với dữ liệu đã
được chuẩn hóa thành ``ProblemInstance``; chúng không mở kết nối SQL Server và
không ghi kết quả ra cơ sở dữ liệu.
"""
