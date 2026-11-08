# Benchmark hiện hành — TARGET_PO80, LT/TH độc lập, 50 vòng

**Lượt bàn giao lần này chỉ chạy ba ablation, không chạy lại GA/PO/lai đầy đủ
hoặc Greedy. Dùng [hướng dẫn ABLATION.md](ABLATION.md), không dùng các lệnh
chạy ba thuật toán chính phía dưới nếu bạn chỉ được giao ablation.** Các
request/suite chính được giữ để xác định và kiểm tra đúng giao thức tham chiếu.

Đây là bộ **V3 TeachingPart** dùng cho lượt chạy mới, không phải bộ SECTION
20 vòng trong `../target_po80_stress/` hoặc `../stress/`. Bộ cũ và kết quả cũ
giữ nguyên. Không dùng các output cũ làm thư mục chạy tiếp cho bộ này.

| Quy mô | Lớp | Phần LT/TH | Khối lặp | Buổi | Gene |
|---|---:|---:|---:|---:|---:|
|Small|12|24|24|232|72|
|Medium|18|36|36|343|108|
|Large|24|48|48|454|144|

LT và TH có thể cùng hoặc khác giảng viên đủ năng lực; mỗi phần giữ cùng
người dạy qua các tuần. Ba snapshot `data/*.json` là bản byte-exact của đầu
vào bộ T50 đã chạy ngày06/11/2026, khóa SHA trong `protocol.json`.

## Giao thức cố định

- GA, PO, GA_PO ×3quy mô×10seed (1–10) = **90 lượt tối ưu**, thêm **3 Greedy**.
- **N30, 50 vòng, trần1530FE gồm30initial**; retry5, decoder20000node,
  repair3lần×20000node, khởi tạo tối đa30000vector thử.
- `GA_PO` gọi **TARGET_PO80**, nhãn `GA_PO_TARGET_PO80.v1`, 24slotGA/6slotPO.
  Không dùng ISLAND80 hoặc PHENO80 làm đối chứng của đợt này.
- Mỗi phương pháp khởi tạo bằng cùng thuật toán, snapshot, tham số và seed;
  quần thể đầu xác định giống nhau. `protocol.json` giữ30SHA của các cohort
  đã lưu để đối chiếu. Không dùng nghiệm cuối của lượt cũ để khởi tạo.
- Nguồn49file package được khóa SHA sau chuẩn hóa CRLF→LF, để cùng commit
  chạy được trên Windows hoặc Linux. Không cần database hoặc tài liệu riêng.
- Không tăng ngân sách khi Greedy chưa tìm được lịch. Không xếp hạng runtime
  khi chạy trên nhiều máy hoặc nhiều tiến trình.

## 1. Cài đặt và kiểm tra — chạy tại thư mục gốc repository

Tất cả máy phải checkout **cùng commit**, không sửa code/config/data sau khi
chia việc. Python3.11 trở lên. Những lệnh dưới đây dùng được trong PowerShell,
CMD, Git Bash và Linux sau khi môi trường Python đã được chọn đúng:

```text
python -m pip install -r requirements.txt
python "Core Algrithms/tools/check_part_t50_benchmark.py"
```

Preflight chỉ đọc/kiểm source, snapshot, checksum, cấu hình, số gene và số buổi;
**không chạy optimizer**. Muốn kiểm thêm một quần thể đầu (có tốn thời gian
khởi tạo, vẫn không chạy optimizer):

```text
python "Core Algrithms/tools/check_part_t50_benchmark.py" --initial small:1
```

Nếu `python` không có trên Git Bash nhưng Windows đã cài Python, dùng `py -3.11`
thay cho `python`. Không dùng cú pháp `$env:PYTHONPATH` trong Git Bash. Sau khi
cài thư viện bằng lệnh trên, các script kiểm tra/chạy benchmark tự thêm đường
dẫn source; không cần đặt PYTHONPATH thủ công cho các script này.

## 2. Chia ba phương pháp cho ba máy

Mỗi người chạy **một lệnh** phù hợp dưới đây; tên `team01` định danh cùng một
đợt mới. Không trộn thư mục từ hai đợt khác nhau.

Máy chạy GA (30lượt):

```text
python -m gapo_timetabling.application.distributed_benchmark run "Core Algrithms/benchmark_configs/target_po80_part_t50/timetable_part_t50_suite.json" --worker GA --output-root "Core Algrithms/distributed_results/PART_T50_team01_GA"
```

Máy chạy PO (30lượt):

```text
python -m gapo_timetabling.application.distributed_benchmark run "Core Algrithms/benchmark_configs/target_po80_part_t50/timetable_part_t50_suite.json" --worker PO --output-root "Core Algrithms/distributed_results/PART_T50_team01_PO"
```

Máy chạy lai mới (30lượt +3Greedy):

```text
python -m gapo_timetabling.application.distributed_benchmark run "Core Algrithms/benchmark_configs/target_po80_part_t50/timetable_part_t50_suite.json" --worker GA_PO --output-root "Core Algrithms/distributed_results/PART_T50_team01_GA_PO"
```

Runner này chạy tuần tự các seed của phương pháp trên từng máy. Đây không phải
controller16job nghiên cứu đã dùng trên máy tác giả; cấu hình thuật toán,
seed, khởi tạo và ngân sách giữ nguyên, thời gian chạy có thể khác. Có thể mở
các lệnh của những phương pháp khác nhau trên cùng một máy nếu đủ tài nguyên;
không mở hai lệnh cùng output-root. Một lượt optimizer hiện vẫn tuần tự.

Nếu bị ngắt, chạy lại **đúng lệnh cũ, cùng commit và output-root**. Runner giữ
JSON hoàn tất đúng checksum/cấu hình và chạy phần thiếu; lượt đang dở phải chạy
lại từ đầu lượt đó, không tiếp tục giữa vòng. Kết quả cần có trạng thái
`COMPLETED`; lỗi tìm lịch và baseline thất bại phải được giữ để kiểm tra.

## 3. Gửi và hợp nhất kết quả

Mỗi người gửi nguyên thư mục `PART_T50_team01_*`, gồm `worker_manifest.json`,
các thư mục quy mô và JSON gốc. Đặt đủ ba thư mục trên máy tổng hợp rồi chạy:

```text
python -m gapo_timetabling.application.distributed_benchmark merge "Core Algrithms/benchmark_configs/target_po80_part_t50/timetable_part_t50_suite.json" --part-root "Core Algrithms/distributed_results/PART_T50_team01_GA" --part-root "Core Algrithms/distributed_results/PART_T50_team01_PO" --part-root "Core Algrithms/distributed_results/PART_T50_team01_GA_PO" --output-root "Core Algrithms/distributed_results/PART_T50_team01_COMBINED"
```

Merge không chạy lại optimizer; kiểm đủ phương pháp/seed, cùng Git revision,
fingerprint cấu hình và checksum. Nó tạo JSON/CSV, báo cáo và các ảnh từ kết
quả đã lưu. Không dùng runtime giữa ba máy để kết luận phương pháp nhanh hơn.

Output mới được `.gitignore` sẵn; không thay quy tắc ignore và không tự đưa
database, Word, ProjectContext/ChangeLogs hoặc kết quả thăm dò riêng lên Git.

## Chạy trọn ba phương pháp trên một máy, theo từng quy mô

Nếu không chia máy, runner thực nghiệm có sẵn chạy cả ba phương pháp và Greedy:

```text
python -m gapo_timetabling.application.experiment "Core Algrithms/benchmark_configs/target_po80_part_t50/experiment_small.json" --output-directory "Core Algrithms/test_results/PART_T50_team01/small" --resume
python -m gapo_timetabling.application.experiment "Core Algrithms/benchmark_configs/target_po80_part_t50/experiment_medium.json" --output-directory "Core Algrithms/test_results/PART_T50_team01/medium" --resume
python -m gapo_timetabling.application.experiment "Core Algrithms/benchmark_configs/target_po80_part_t50/experiment_large.json" --output-directory "Core Algrithms/test_results/PART_T50_team01/large" --resume
```

Các lệnh này cũng chạy tuần tự, không nhận tham số `--workers16`. Chỉ chạy khi
cần một đợt thực nghiệm mới; không bắt buộc chạy lại để đọc kết quả đã hoàn tất.
