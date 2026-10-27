# Dữ liệu demo khan hiếm tài nguyên

> Cập nhật D094 ngày 19/10/2026: lịch dùng recurring pattern cố định
> thứ–tiết–địa điểm xuyên suốt các tuần hoạt động. `ClassSession` vẫn là
> occurrence tuần; một gene lịch điều khiển cả nhóm occurrence.

File `large_timetable_snapshot.json` là snapshot đầu vào dùng để chạy trực tiếp
CLI hybrid hiện tại. Dữ liệu được cố ý thiết kế khó, có cạnh tranh giảng viên,
phòng và khung giờ thay vì cung cấp dư tài nguyên. Đây vẫn là dữ liệu giả lập có
cấu trúc giống snapshot application Python sẽ xuất trong luồng production; file không thay
thế SQL Server và không phải dữ liệu chính thức của HUIT.

## Quy mô

- 9 lớp học phần nhưng chỉ có 4 giảng viên. Mỗi giảng viên phụ trách từ 2 đến 3
  lớp học phần; lý thuyết và thực hành của cùng lớp vẫn dùng chung giảng viên.
- Mỗi lớp có một phần lý thuyết và một phần thực hành; hai phần dùng chung
  giảng viên theo quy tắc nghiệp vụ hiện hành.
- 18 phần giảng dạy, 18 kế hoạch hợp lệ và 108 buổi cần xếp trong 6 tuần.
- Chỉ có 4 phòng. Các phần lý thuyết và thực hành vẫn cạnh tranh tài nguyên
  theo loại phòng, thiết bị, lịch bận và khung tiết.
- Các phòng đều đủ sức chứa cho fixture. Độ khó vẫn đến từ số phòng ít, loại
  phòng, thiết bị, lịch bận và xung đột tài nguyên. Sức chứa là hard constraint
  và được kiểm tra riêng bằng các test biên.
- Lịch có các ngày occurrence trong 6 tuần; generator không đánh dấu ngày
  nghỉ/học bù vì trạng thái đó không còn tham gia tối ưu.
- 12 tiết mỗi ngày, tách thành ca sáng và ca chiều.
- 34 khoảng availability của giảng viên, trong đó có 22 khoảng `UNAVAILABLE`;
  nhiều giảng viên bị cấm trọn ngày hoặc từng nửa ngày lặp lại mỗi tuần.
- 14 khoảng availability của phòng, trong đó có 11 khoảng `UNAVAILABLE`, gồm
  bảo trì lặp lại và sự cố tại ngày cụ thể.
- Encoder sinh 2.217 option nguyên tử cho 108 occurrence. Sau phép giao theo
  tuần, 18 gene recurring còn tổng 312 pattern, từ 7 đến 26 pattern/gene.

`expected_enrollment` là chỉ tiêu lập kế hoạch đã duyệt dùng để kiểm tra hard
capacity. Dữ liệu không chứa danh sách sinh viên vì hệ thống lập lịch trước
khi đăng ký.

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
python -m gapo_timetabling.application.demo_cli demo_data/large_timetable_snapshot.json `
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
  -> application Python đọc dữ liệu và khóa PlanningScenario
  -> application Python tạo snapshot JSON bất biến
  -> core Python đọc snapshot và tối ưu
  -> application Python lưu OptimizationRun và TimetableEntry vào SQL Server
```

Core thuật toán không đọc trực tiếp database. Trong demo hiện tại, file JSON
đóng vai trò snapshot đã được tầng application tạo sẵn để kiểm tra optimizer
độc lập.

## Chạy bằng hợp đồng JSON dùng cho tích hợp

File `optimization_run_request.example.json` minh họa hợp đồng
`optimization-run-request.v1`. Từ thư mục `Core Algrithms`, chạy:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.application.run_cli `
  demo_data/optimization_run_request.example.json `
  --result test_results/optimization_run_result.json
```

Đổi trường `algorithm` thành `GA`, `PO` hoặc `GA_PO` để chọn optimizer. CLI
không phân tích tham số thuật toán từ câu lệnh; toàn bộ cấu hình nằm trong
request JSON để application có thể lưu và tái lập lần chạy. Kết quả được ghi theo
`optimization-run-result.v1`, gồm checksum snapshot, mapping gene–option, ba
tầng fitness, breakdown, metrics, convergence và danh sách phân công đủ khóa
để lưu thành `TimetableEntry`.

Đây là hợp đồng chạy độc lập của Python. Transaction lưu SQL Server đã thuộc
tầng application; timeout, hủy tiến trình và theo dõi tiến độ trong lúc chạy
vẫn là phần chưa hoàn thành.

## Chạy pilot so sánh GA, PO và GA–PO

### Smoke test một seed

Khi chỉ cần kiểm tra nhanh toàn bộ runner và artifact, dùng cấu hình một seed:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.application.experiment `
  demo_data/timetable_experiment_smoke.json `
  --output-directory test_results/timetable_experiment_smoke_latest
python demo_data/analyze_dynamic_assignment_pilot.py `
  --experiment-directory test_results/timetable_experiment_smoke_latest
```

Smoke test chạy GA, PO và GA–PO trên cùng snapshot, seed 42, population 20 và
ngân sách lý thuyết 220 FE. Kết quả chỉ xác nhận pipeline và validator hoạt
động; một seed và số FE thực tế khác nhau giữa các thuật toán không đủ để kết
luận thuật toán nào tốt hơn.

File `timetable_experiment_pilot.json` chạy tuần tự ba thuật toán với ba seed.
Mọi run dùng cùng snapshot, population size, ngân sách FE, decoder và repair:

```powershell
$env:PYTHONPATH = "src"
python -m gapo_timetabling.application.experiment `
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
python -m gapo_timetabling.application.experiment `
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

## Dữ liệu đánh giá khả năng mở rộng

`generate_scalability_snapshots.py` tạo ba snapshot D109 trong thư mục
`scalability/`. Đây mới là dữ liệu chuẩn bị cho thực nghiệm; script không chạy
Greedy, GA, PO hoặc GA–PO.

| Profile | Lớp | Part | Occurrence | Gene | Áp lực tải |
|---|---:|---:|---:|---:|---:|
| Small | 3 | 6 | 58 | 9 | 29,17% |
| Medium | 7 | 14 | 132 | 21 | 66,67% |
| Large | 10 | 20 | 190 | 30 | 76,67% |

Ba profile giữ sáu giảng viên, năm địa điểm và cùng availability. Profile lớn
nâng trần tải mỗi giảng viên từ 120 lên 150 tiết để không tạo dữ liệu vô nghiệm;
tổng nhu cầu tăng nhanh hơn tổng tải nên áp lực tài nguyên vẫn cao hơn bộ vừa.

Tạo lại dữ liệu từ thư mục project:

```powershell
$env:PYTHONPATH = "Core Algrithms/src"
python "Core Algrithms/demo_data/generate_scalability_snapshots.py"
```

`scalability/manifest.json` lưu kích thước và SHA-256 của từng file, đồng thời
đánh dấu `benchmark_executed: false`. Test chỉ chạy preflight và một feasibility
smoke xác định để chứng minh mỗi bộ có ít nhất một lịch hợp lệ; không sinh số
liệu so sánh thuật toán.

