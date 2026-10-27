# Cấu hình benchmark thời khóa biểu

Thư mục này khóa cấu hình thực nghiệm của học kỳ `2027_HK1`:

- Greedy First Feasible chạy một lần làm mốc tham khảo xác định.
- GA, PO và GA–PO dùng cùng population 30, 20 vòng xử lý quần thể và cùng seed.
- Pilot dùng seed 1–3; bộ chính thức dùng seed 1–10.
- Ba optimizer dùng chung snapshot, Decoder, Repair, Validator và Fitness.
- `max_fitness_evaluations=630` là giới hạn lý thuyết tương ứng
  `30 + 30 × 20`; FE thực tế có thể thấp hơn do vector bị loại trước Fitness.
  Báo cáo phải gọi đây là giao thức cùng population/cùng số vòng và trình bày
  FE thực tế như chỉ số hiệu quả, không tuyên bố FE bằng nhau.
- Baseline dùng chung Decoder, Validator và Fitness nhưng chỉ dựng một lịch;
  nó không được diễn giải là phương pháp có cùng ngân sách với ba optimizer.

Để ba người chạy riêng GA, PO và GA–PO trên các bộ Small–Medium–Large rồi hợp
nhất kết quả, dùng bộ lệnh trong
[`distributed/README.md`](distributed/README.md). Đây là giao thức chính để
đánh giá khả năng mở rộng; cấu hình đơn bên dưới được giữ cho thực nghiệm tuần
tự trên một máy.

## Chuẩn bị snapshot đã khóa

Chạy tại thư mục gốc project:

```powershell
$env:PYTHONPATH="Core Algrithms/src"
python -m gapo_timetabling build-snapshot 11 --output "Core Algrithms/demo_data/benchmark_snapshot_2027_HK1.json"
```

Lệnh phải in checksum:

```text
5b2f2c87fb1f97cdf484ccc3aec1e27d2548872de6209241c4132d3e38080a65
```

Nếu checksum khác, không sửa tùy tiện trường checksum trong request. Cần kiểm
tra scenario hoặc dữ liệu đã thay đổi và quyết định lại snapshot benchmark.

## Chạy pilot

```powershell
$env:PYTHONPATH="Core Algrithms/src"
python -m gapo_timetabling.application.experiment `
  "Core Algrithms/benchmark_configs/timetable_benchmark_pilot_2027_HK1.json" `
  --output-directory "Core Algrithms/test_results/timetable_benchmark_pilot_light_2027_HK1"
```

## Chạy chính thức

Chỉ chạy sau khi pilot hoàn thành kỹ thuật và không thay đổi tham số:

```powershell
$env:PYTHONPATH="Core Algrithms/src"
python -m gapo_timetabling.application.experiment `
  "Core Algrithms/benchmark_configs/timetable_benchmark_official_2027_HK1.json" `
  --output-directory "Core Algrithms/test_results/timetable_benchmark_official_light_2027_HK1"
```

Runner chạy tuần tự để tránh các thuật toán tranh chấp CPU. Mỗi optimizer xử
lý cùng 20 vòng quần thể; runner không cắt run theo thời gian và lưu runtime,
FE thực tế cùng lỗi decode để so sánh. Không chạy đồng thời web optimizer.

## Artifact và biểu đồ

Mỗi run được ghi JSON ngay khi hoàn thành. Sau đó runner ghi
`raw_results.csv`, `summary.csv`, `convergence.csv`,
`experiment_metadata.json` và `plot_manifest.json`. Các ảnh được tạo tự động:

1. `01_convergence.png`: hội tụ theo FE của từng seed và đường trung vị.
2. `02_fitness_comparison.png`: phân bố `Q_general` và `Q_lecturer`.
3. `03_runtime_and_fe.png`: runtime và FE thực tế.
4. `04_search_diagnostics.png`: lần thử nghiệm, lỗi decode, con bị loại và repair.
5. `05_rank_and_wins.png`: hạng trung bình và số seed đứng đầu.
6. `06_objective_space.png`: vị trí nghiệm trong không gian hai Q.
7. `07_per_seed_scores.png`: kết quả ghép cặp trên từng seed dùng chung.
8. `08_success_rate.png`: tỷ lệ hoàn thành với lịch hợp lệ.
9. `09_best_timetable_<ALGORITHM>.png`: thời khóa biểu tốt nhất riêng của GA,
   PO, GA–PO và Greedy; mỗi ảnh có CSV lịch tương ứng và một file metadata ghi
   chính xác run nguồn.

Greedy xuất hiện trong các ảnh chất lượng/chi phí phù hợp nhưng không xuất hiện
trong hội tụ hay xếp hạng nhiều seed vì baseline chỉ chạy một lần.

Nếu ảnh bị thiếu hoặc muốn đổi cách trình bày sau khi benchmark đã hoàn thành,
không chạy lại thuật toán. Dùng đúng config và thư mục kết quả cũ:

```powershell
python -m gapo_timetabling.application.experiment `
  "Core Algrithms/benchmark_configs/timetable_benchmark_official_2027_HK1.json" `
  --output-directory "Core Algrithms/test_results/timetable_benchmark_official_light_2027_HK1" `
  --plots-only
```

`plot_manifest.json` ghi rõ ảnh nào đã tạo thành công và lỗi của từng ảnh nếu có.
