# Cài đặt và mở ứng dụng xếp thời khóa biểu

## Chuẩn bị một lần trên Windows

1. Cài Python 3.11 trở lên. Dự án đã được kiểm tra bằng Python 3.12.
2. Cài và khởi động SQL Server; SSMS là công cụ quản trị, không thay thế dịch vụ SQL Server.
3. Cài Microsoft ODBC Driver 17 hoặc 18 for SQL Server.
4. Mở terminal ở thư mục gốc dự án, nơi có `requirements.txt`, rồi chạy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Cấu hình kết nối

Sao chép `.env.example` thành `.env` tại gốc dự án nếu chưa có file này.
Điền SQL Server, database riêng và tài khoản của máy triển khai. Ví dụ:

```dotenv
DB_URL=jdbc:sqlserver://localhost\SQLEXPRESS;databaseName=KhoaLuanDemo;encrypt=true;trustServerCertificate=true
DB_USERNAME=ten_tai_khoan_SQL
DB_PASSWORD='mat_khau_cua_ban'
```

`DB_URL` dùng định dạng JDBC như ví dụ. Máy chủ dùng cổng cụ thể có thể ghi
`jdbc:sqlserver://localhost:1433;databaseName=KhoaLuanDemo;encrypt=true;trustServerCertificate=true`.
Đổi cả ba giá trị theo máy của người nhận. Tài khoản SQL cần được cấp quyền
đăng nhập; ứng dụng không tự tạo tài khoản, đổi mật khẩu hoặc cấu hình SQL Server.
Biến môi trường `DB_*` đã khai báo có ưu tiên hơn file `.env`.

## Tạo database một lần bằng script SQL

1. Mở `Script/KHOI_TAO_DATABASE.sql` bằng SSMS và kết nối SQL Server.
2. Tên database mặc định là `KhoaLuanDemo`. Nếu muốn tên khác, thay tất cả
   `KhoaLuanDemo` trong script bằng tên đó và sửa `databaseName` trong `.env`
   cho khớp. Không dùng database hệ thống.
3. Chạy toàn bộ script. Script tạo database nếu chưa có, tạo 34 bảng cùng các
   khóa/chỉ mục và dữ liệu nền. Nếu database đã có bảng, script dừng để bảo
   vệ dữ liệu; không xóa hoặc tự nâng cấp database cũ.
4. Kiểm tra dòng kết quả cuối: 34 bảng, 16 tiết học, 4 quy tắc thời lượng,
   9 khối tiết, 13 cấu hình ràng buộc; số học kỳ và lượt tối ưu bằng 0.

Dữ liệu nền có các trọng số mềm và ngưỡng dạy liên tục mặc định. Lớp, môn,
giảng viên, phòng, học kỳ và kết quả demo không được chèn vào database.
Tài khoản chạy script cần quyền tạo database/bảng; nếu không có quyền thì
nhờ quản trị viên thực hiện. Các bảng và dữ liệu nền được tạo nguyên tử trong
một transaction. Nếu lỗi, database mới có thể còn tồn tại nhưng các bảng
trong lần khởi tạo được rollback.

## Mở ứng dụng

Bấm đúp `CHAY_UNG_DUNG.cmd`. Giữ cửa sổ dòng lệnh khi sử dụng. Trình duyệt
mở tại `http://127.0.0.1:8000`; nhấn `Ctrl+C` trong cửa sổ để dừng web.
Web đọc `.env` để kết nối; không tự tạo database/bảng khi khởi động.

Database mới chưa có học kỳ, lớp hay lịch cũ. Vào trang Dữ liệu để nhập file
Excel demo được bàn giao hoặc nhập tay, sau đó Chuẩn bị → Thuật toán → Thời
khóa biểu. Muốn có sẵn lịch đã chạy phải khôi phục bản sao lưu database riêng.

Sau khi đổi `.env`, dừng web rồi mở lại khi không có lượt tối ưu đang chạy.
File `.env` chứa mật khẩu không được đưa lên Git. Không chạy `Script/script.sql`
trên database cần giữ: file đó là script reset cho phát triển và có lệnh xóa bảng.
