# Dữ liệu demo khan hiếm tài nguyên

> Cập nhật D094 ngày 19/10/2026: lịch dùng recurring pattern cố định
> thứ–tiết–địa điểm xuyên suốt các tuần hoạt động. `ClassSession` vẫn là
> occurrence tuần; một gene lịch điều khiển cả nhóm occurrence.

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
- Chỉ có 4 phòng. Các phần lý thuyết và thực hành vẫn cạnh tranh tài nguyên
  theo loại phòng, thiết bị, lịch bận và khung tiết.
- Sức chứa phòng từ 30 đến 45 trong khi chỉ tiêu phần lớn từ 56 đến 80. Phòng
  thiếu chỗ vẫn là option hợp lệ nhưng nhận điểm phạt mềm theo mô hình đã chốt.
- Lịch có các ngày occurrence trong 6 tuần; generator không đánh dấu ngày
  nghỉ/học bù vì trạng thái đó không còn tham gia tối ưu.
- 12 tiết mỗi ngày, tách thành ca sáng và ca chiều.
- 34 khoảng availability của giảng viên, trong đó có 22 khoảng `UNAVAILABLE`;
  nhiều giảng viên bị cấm trọn ngày hoặc từng nửa ngày lặp lại mỗi tuần.
- 14 khoảng availability của phòng, trong đó có 11 khoảng `UNAVAILABLE`, gồm
  bảo trì lặp lại và sự cố tại ngày cụ thể.
- Encoder sinh 2.217 option nguyên tử cho 108 occurrence. Sau phép giao theo
  tuần, 18 gene recurring còn tổng 312 pattern, từ 7 đến 26 pattern/gene.

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

Các kết quả demo trước D094 là lịch sử của vector theo tuần. Sau D094 cần chạy
lại CLI để tạo artifact mới; cấu hình nhỏ chỉ chứng minh dữ liệu khả thi và
không được dùng để kết luận thuật toán nào tốt nhất.

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

`timetable.csv` giữ toàn bộ các buổi của học kỳ để kiểm tra và lưu kết quả.
Riêng `02_timetable_detail.png` chỉ vẽ một tuần đại diện để tránh lặp lại cùng
mẫu lịch ở nhiều tuần và giúp nội dung trong ảnh dễ đọc hơn. Code chọn tuần có
nhiều buổi nhất; nếu số buổi bằng nhau thì chọn tuần sớm nhất.

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

## Chạy bằng hợp đồng JSON dùng cho tích hợp

File `optimization_run_request.example.json` minh họa hợp đồng
`optimization-run-request.v1`. Từ thư mục `Core Algrithms`, chạy:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.run_cli `
  demo_data/optimization_run_request.example.json `
  --result test_results/optimization_run_result.json
```

Đổi trường `algorithm` thành `GA`, `PO` hoặc `GA_PO` để chọn optimizer. CLI
không phân tích tham số thuật toán từ câu lệnh; toàn bộ cấu hình nằm trong
request JSON để Java có thể lưu và tái lập lần chạy. Kết quả được ghi theo
`optimization-run-result.v1`, gồm checksum snapshot, mapping gene–option, ba
tầng fitness, breakdown, metrics, convergence và danh sách phân công đủ khóa
để lưu thành `TimetableEntry`.

Đây là nền hợp đồng phía Python. Timeout, hủy tiến trình, theo dõi tiến độ trong
lúc chạy và transaction lưu SQL Server sẽ do tầng điều phối Java bổ sung sau.

## Chạy pilot so sánh GA, PO và GA–PO

File `timetable_experiment_pilot.json` chạy tuần tự ba thuật toán với ba seed.
Mọi run dùng cùng snapshot, population size, ngân sách FE, decoder và repair:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.experiment `
  demo_data/timetable_experiment_pilot.json `
  --output-directory test_results/timetable_experiment/pilot
```

Kết quả gồm JSON gốc của chín run, `raw_results.csv`, `convergence.csv`,
`summary.csv`, metadata và hai ảnh so sánh. Pilot chỉ kiểm tra giao thức và
khả năng tạo artifact; không dùng ba seed cùng ngân sách 18 FE để kết luận
thuật toán nào tốt nhất. Thực nghiệm báo cáo phải dùng cấu hình/ngân sách được
công bố trước và số seed đủ lớn.

## Pilot phân công giảng viên động trên dữ liệu khó

`generate_dynamic_assignment_snapshot.py` tạo lại snapshot
`problem-instance.v2` xác định dùng để kiểm tra D093. Fixture không phải dữ
liệu thuận lợi được dựng để thuật toán dễ đạt điểm đẹp:

- 9 lớp học phần thuộc 5 môn, 18 phần lý thuyết/thực hành và 108 buổi trong
  6 tuần;
- 5 giảng viên, 19 quan hệ năng lực môn–giảng viên và nhiều người có thể cạnh
  tranh cho cùng lớp;
- 432 tiết phải phân công trong khi tổng tải tối đa chỉ là 480 tiết, tức chỉ
  dư 48 tiết trên toàn hệ thống;
- 4 phòng khan hiếm, có yêu cầu loại phòng/thiết bị, lịch bận phòng và lịch
  bận giảng viên;
- vector có 9 gene phân công và 18 gene recurring schedule, tổng 27 chiều;
  encoder sinh 5.987 option nguyên tử session–lecturer rồi rút thành 742
  pattern có điều kiện theo giảng viên cho 18 nhóm.

Tạo lại snapshot và chạy pilot 3 thuật toán × 5 seed:

```powershell
$env:PYTHONPATH = "src"
python demo_data/generate_dynamic_assignment_snapshot.py
python -m gapo_timetabling.experiment `
  demo_data/timetable_experiment_dynamic_v2.json `
  --output-directory `
  test_results/timetable_experiment_dynamic_v2_pilot_20261017
python demo_data/analyze_dynamic_assignment_pilot.py
```

Các artifact 15 run hiện có được tạo trước D094 và chỉ giữ để truy nguyên.
Phải chạy lại experiment rồi giải mã/validator độc lập trước khi dùng số liệu
hoặc ảnh cho mô hình recurring schedule hiện hành.

Pilot này chưa phải benchmark lịch chính thức. Cùng một giới hạn FE lý thuyết
nhưng số FE thực tế của PO và GA–PO thấp hơn GA vì cá thể không giải mã được
không được gọi fitness. Do đó các median/rank hiện tại chỉ dùng để kiểm tra
pipeline và quan sát hành vi; chưa được dùng để kết luận thuật toán nào tốt
nhất. Protocol chính thức phải xử lý công bằng ngân sách thực tế trước khi
chạy khoảng 30 seed.

