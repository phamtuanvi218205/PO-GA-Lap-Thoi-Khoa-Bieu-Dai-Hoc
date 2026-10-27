# Benchmark phân tán trên ba máy

Bộ lệnh này chạy cùng giao thức trên ba mức dữ liệu:

| Mức | Lớp học phần | Số chiều vector | Số buổi |
| --- | ---: | ---: | ---: |
| Small | 3 | 9 | 58 |
| Medium | 7 | 21 | 132 |
| Large | 10 | 30 | 190 |

GA, PO và GA–PO đều dùng population 30, tối đa 630 FE và các seed 1–10.
Mỗi người chạy trọn một thuật toán trên cả ba mức. Worker GA–PO chạy thêm
Greedy First Feasible một lần cho mỗi mức vì baseline này xác định và chạy
nhanh.

## 1. Chuẩn bị giống nhau trên cả ba máy

Mỗi người phải checkout đúng cùng một commit đã được push. Mở terminal tại thư
mục gốc `KhoaLuan`, sau đó khai báo source Python:

```powershell
$env:PYTHONPATH="Core Algrithms/src"
```

Không sửa snapshot, request, seed hoặc tham số thuật toán sau khi chia việc.
`worker_manifest.json` sẽ lưu Git revision, môi trường chạy, checksum và
fingerprint giao thức để lệnh merge kiểm tra.

Runner sẽ từ chối bắt đầu nếu source còn thay đổi chưa commit. Vì vậy người
chuẩn bị code phải commit và push toàn bộ trước; hai người còn lại pull đúng
commit đó rồi mới chạy.

## 2. Lệnh của từng người

Người chạy GA:

```powershell
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/distributed/timetable_scalability_suite_2027_HK1.json" `
  --worker GA `
  --output-root "Core Algrithms/distributed_results/GA"
```

Người chạy PO:

```powershell
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/distributed/timetable_scalability_suite_2027_HK1.json" `
  --worker PO `
  --output-root "Core Algrithms/distributed_results/PO"
```

Người chạy GA–PO và Greedy:

```powershell
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/distributed/timetable_scalability_suite_2027_HK1.json" `
  --worker GA_PO `
  --output-root "Core Algrithms/distributed_results/GA_PO"
```

Nếu terminal hoặc máy bị ngắt, chạy lại đúng lệnh cũ. Runner tự dùng lại JSON
`COMPLETED` đúng checksum và chỉ chạy phần còn thiếu. Không xóa hoặc sửa tay
các file trong thư mục kết quả.

Khi hoàn thành, sự kiện cuối phải có `status: COMPLETED`. Số run dự kiến:

- GA: 30 run tối ưu.
- PO: 30 run tối ưu.
- GA–PO: 30 run tối ưu và 3 baseline Greedy.

Mỗi người gửi nguyên thư mục `GA`, `PO` hoặc `GA_PO`, kể cả
`worker_manifest.json`; không cần gom từng file JSON.

## 3. Hợp nhất và sinh ảnh

Trên máy tổng hợp, đặt ba thư mục đúng vị trí trên hoặc truyền đường dẫn thực
tế của chúng. Chạy:

```powershell
$env:PYTHONPATH="Core Algrithms/src"
python -m gapo_timetabling.application.distributed_benchmark merge `
  "Core Algrithms/benchmark_configs/distributed/timetable_scalability_suite_2027_HK1.json" `
  --part-root "Core Algrithms/distributed_results/GA" `
  --part-root "Core Algrithms/distributed_results/PO" `
  --part-root "Core Algrithms/distributed_results/GA_PO" `
  --output-root "Core Algrithms/distributed_results/COMBINED"
```

Lệnh merge không chạy lại optimizer. Nó dừng nếu thiếu worker, thiếu seed,
khác Git revision, khác checksum hoặc khác cấu hình. Nếu thư mục đích đã chứa
một JSON khác nội dung, lệnh cũng không ghi đè.

Trong `COMBINED/small`, `COMBINED/medium` và `COMBINED/large` có JSON nguồn,
CSV tổng hợp và các ảnh `01`–`09`. Thư mục `COMBINED` có thêm:

- `scalability_summary.csv`;
- `10_scalability_quality.png`;
- `11_scalability_success_rate.png`;
- `12_scalability_fitness_evaluations.png`;
- `merged_manifest.json`.

Do ba thuật toán chạy trên ba máy khác nhau, runtime chỉ được lưu để truy vết.
Không dùng runtime để kết luận thuật toán nào nhanh hơn. Kết luận chính dựa vào
Q_general, Q_lecturer, tỷ lệ tạo lịch hợp lệ, hội tụ theo FE, FE thực tế và sự
thay đổi khi quy mô tăng.
