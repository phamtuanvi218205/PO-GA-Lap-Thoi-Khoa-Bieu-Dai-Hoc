# Dữ liệu demo khan hiếm tài nguyên

File `large_timetable_snapshot.json` là snapshot đầu vào dùng để chạy trực tiếp
CLI hybrid hiện tại. Dữ liệu được cố ý thiết kế khó, có cạnh tranh giảng viên,
phòng và khung giờ thay vì cung cấp dư tài nguyên. Đây vẫn là dữ liệu giả lập có
cấu trúc giống snapshot Java sẽ xuất trong luồng production; file không thay
thế SQL Server và không phải dữ liệu chính thức của HUIT.

## Quy mô

- 9 lớp học phần nhưng chỉ có 4 giảng viên. Mỗi giảng viên phụ trách từ 2 đến 3
  lớp học phần; lý thuyết và thực hành của cùng lớp vẫn dùng chung giảng viên.
- Mỗi lớp có một phần lý thuyết và một phần thực hành; hai phần dùng chung
  giảng viên theo quy tắc nghiệp vụ hiện hành.
- 18 phần giảng dạy, 18 kế hoạch hợp lệ và 108 buổi cần xếp trong 6 tuần.
- Chỉ có 4 phòng. Toàn bộ phần lý thuyết cạnh tranh một phòng có máy chiếu;
  sáu phần thực hành yêu cầu cấu hình cao chỉ dùng được một phòng máy.
- Sức chứa phòng từ 30 đến 45 trong khi chỉ tiêu phần lớn từ 56 đến 80. Phòng
  thiếu chỗ vẫn là option hợp lệ nhưng nhận điểm phạt mềm theo mô hình đã chốt.
- 32 ngày trong lịch, gồm hai ngày nghỉ và hai ngày thứ Bảy được phép học bù.
- 12 tiết mỗi ngày, tách thành ca sáng và ca chiều.
- 34 khoảng availability của giảng viên, trong đó có 22 khoảng `UNAVAILABLE`;
  nhiều giảng viên bị cấm trọn ngày hoặc từng nửa ngày lặp lại mỗi tuần.
- 14 khoảng availability của phòng, trong đó có 11 khoảng `UNAVAILABLE`, gồm
  bảo trì lặp lại và sự cố tại ngày cụ thể.
- Encoder sinh 704 option cho 108 gene; mỗi gene chỉ còn từ 2 đến 13 option.
  Không gian kết hợp thô vẫn xấp xỉ `10^83,55`, trong khi xung đột tài nguyên
  giữa các gene lớn hơn đáng kể so với bộ dữ liệu cũ.

`expected_enrollment` chỉ là sĩ số dự kiến để tính tiêu chí sức chứa mềm. Dữ
liệu không chứa danh sách sinh viên vì hệ thống lập lịch trước khi đăng ký.

## Tạo lại dữ liệu xác định

File JSON được sinh từ script để các thay đổi fixture có thể kiểm tra và tái
lập, thay vì chỉnh tay hàng nghìn dòng:

```powershell
python demo_data/generate_resource_constrained_snapshot.py
```

Script luôn tạo cùng một snapshot; nó không dùng dữ liệu ngẫu nhiên.

## Chạy demo nhanh

Từ thư mục `Core Algrithms`, trên PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.hybrid demo_data/large_timetable_snapshot.json `
  --population-size 6 `
  --iterations 2 `
  --seed 42 `
  --max-initialization-attempts 1000 `
  --max-offspring-attempts 3 `
  --max-decode-nodes 20000
```

Cấu hình trên dùng để kiểm tra nhanh luồng đầu-cuối, không dùng để kết luận
chất lượng thuật toán. Có thể tăng `--population-size` và `--iterations` cho
thực nghiệm dài hơn; thời gian chạy sẽ tăng theo số lần đánh giá fitness.

Lần kiểm tra tối thiểu ngày 08/10/2026 với quần thể 2, một vòng lặp và seed 42
hoàn tất 4 FE, tìm được đủ 108 phân công và có 0 vi phạm cứng. Kết quả trải
trên nhiều ngày từ thứ Hai đến thứ Bảy. Cấu hình nhỏ này chỉ chứng minh dữ liệu
khó vẫn khả thi; không dùng để kết luận chất lượng hay độ ổn định của thuật
toán. Giá trị thời gian chỉ mang tính tham khảo vì phụ thuộc máy và tải hệ
thống.

Mỗi lần chạy mặc định cập nhật đúng một thư mục
`test_results/timetable_demo/latest` để tránh tạo nhiều thư mục kết quả rác:

```text
latest/
├── run_summary.json
├── convergence.csv
├── timetable.csv
├── 01_convergence.png
└── 02_timetable_detail.png
```

Dùng `--output-directory <đường-dẫn>` để chọn nơi lưu khác hoặc `--no-report`
nếu chỉ muốn xem kết quả trên terminal.

## Vị trí của database trong luồng hoàn chỉnh

```text
SQL Server
  -> Java đọc dữ liệu và khóa PlanningScenario
  -> Java tạo snapshot JSON bất biến
  -> Python đọc snapshot và tối ưu
  -> Python trả kết quả cho Java
  -> Java lưu OptimizationRun và TimetableEntry vào SQL Server
```

Python không đọc trực tiếp database. Trong demo hiện tại, file JSON đóng vai
trò snapshot đã được Java tạo sẵn để có thể kiểm tra optimizer độc lập.

