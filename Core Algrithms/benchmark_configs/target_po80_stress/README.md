# Benchmark nặng — Priority + Placement / TARGET_PO80

**Bộ hiện hành V3/T50 và ba ablation đã chuyển sang
[target_po80_part_t50/ABLATION.md](../target_po80_part_t50/ABLATION.md).**
Thư mục này giữ nguyên mô hình SECTION/20vòng làm lịch sử; không chạy lại nó
để thay thế các đối chứng ablation của mô hình LT/TH độc lập.

**Lưu ý phạm vi phân công:** ba request trong thư mục này vẫn trỏ snapshot v2
SECTION, D60/90/120. Code hiện đã hỗ trợ v3 TEACHING_PART với LT/TH độc lập;
suite này chưa được chuyển sang mô hình đó. Khi đánh giá mô hình mới cần
snapshot v3, D72/108/144 và quần thể khởi tạo mới dùng chung giữa các phương pháp.
Không chạy suite v2 rồi gọi là benchmark v3; không đổi snapshot/nhãn kết quả cũ.

Ngày 05/11/2026: GA_PO của lượt chạy mới là TARGET_PO80, có nhãn cơ chế riêng
trong ba request. Đổi cơ chế không chạy lại benchmark hoặc đổi kết quả D155.

D158 đóng gói lại đúng snapshot D150 đã dùng ở D155; không sinh hoặc sửa dữ liệu.
Các fixture tổng hợp có quan hệ mở rộng, không phải ba trường độc lập.

| Mức | Lớp | Khối lặp | Buổi | D | Giảng viên | Phòng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Small | 12 | 24 | 232 | 60 | 6 | 5 |
| Medium | 18 | 36 | 343 | 90 | 6 | 5 |
| Large | 24 | 48 | 454 | 120 | 6 | 5 |

N30, 20 vòng, trần630FE gồm30initial, seed1–10; retry5/node20000/repair3/
init30000. GA_PO mặc định TARGET_PO80 với24slotGA/6slotPO; Priority+Placement hard-only dùng chung
GA/PO/lai. Ba request có checksum canonical khóa snapshot; test còn khóa SHA
byte của từng file. Không đổi data giữa worker hoặc trộn kết quả lai50/50 cũ.

Chạy một quy mô (chỉ khi người dùng yêu cầu):

```powershell
$env:PYTHONPATH="Core Algrithms/src"
python -m gapo_timetabling.application.experiment `
  "Core Algrithms/benchmark_configs/target_po80_stress/experiment_small.json" `
  --output-directory "Core Algrithms/test_results/NEW_STRESS_OUTPUT/small"
```

Suite `timetable_stress_suite.json` dùng cùng runner phân tán hiện có, thay
đường dẫn suite cũ bằng đường dẫn file này. Runner phân tán yêu cầu source sạch
và cùng revision; lần tích hợp TARGET_PO80 không tự commit/push hoặc chạy benchmark.

Suite mới gồm GA/PO/GA_PO: **90 optimizer + 3 Greedy**, không gọi là một lần
chạy lại D155120run. D155 có thêm HYBRID50 để làm đối chứng lịch sử, giữ nguyên
trong `test_results/island_official_stress_20261101`. Tích hợp không chạy thêm
optimizer, không gắn nhãn lại HYBRID50 thành ISLAND80.

Đọc cả kết quả cuối20vòng và exact common FE; FE không tính decode/repair
thất bại nên không đại diện toàn bộ chi phí. Không xếp hạng runtime các job
chạy song song hoặc khẳng định ưu thế thống kê từ tỷ lệ thắng nhỏ.

## Kết quả đã đồng bộ, không cần chạy lại để đọc

[Bộ kết quả được chọn](../../benchmark_results/README.md) gồm D155 đủ120optimizer+
3Greedy và D1593run xác nhận tích hợp. Trong gói, ISLAND80 là tên thí nghiệm
của cơ chế ISLAND80 trước đây; HYBRID50 là đối chứng cũ, không đổi nhãn.
Gói này không phải kết quả của TARGET_PO80. Nghiên cứu TARGET_PO80 và hai
ablation ngày05/11 được giữ riêng trong test_results; không sửa nhãn số liệu cũ.
Kết quả cũ không phải thư mục resume cho code mới. Muốn kiểm checksum/dữ liệu:

```powershell
python "Core Algrithms/tools/sync_selected_benchmark.py" --verify
```

Lệnh chỉ đọc/kiểm file, không chạy optimizer, không kết nối database.

## Lệnh mới cho ba máy (chỉ chạy khi có yêu cầu)

Tại thư mục gốc repo, cả ba máy cài cùng source và dùng cùng commit sạch.
Các output dưới đây là **thư mục mới**, không ghi vào kết quả D155 hoặc bộ nhỏ cũ.

```powershell
$env:PYTHONPATH="Core Algrithms/src"
# Máy1
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/target_po80_stress/timetable_stress_suite.json" `
  --worker GA --output-root "Core Algrithms/distributed_results/STRESS_NEW_GA"
# Máy2
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/target_po80_stress/timetable_stress_suite.json" `
  --worker PO --output-root "Core Algrithms/distributed_results/STRESS_NEW_PO"
# Máy3: GA_PO TARGET_PO80 + Greedy
python -m gapo_timetabling.application.distributed_benchmark run `
  "Core Algrithms/benchmark_configs/target_po80_stress/timetable_stress_suite.json" `
  --worker GA_PO --output-root "Core Algrithms/distributed_results/STRESS_NEW_GA_PO"
```

Chỉ merge kết quả của **cùng đợt chạy mới**:

```powershell
python -m gapo_timetabling.application.distributed_benchmark merge `
  "Core Algrithms/benchmark_configs/target_po80_stress/timetable_stress_suite.json" `
  --part-root "Core Algrithms/distributed_results/STRESS_NEW_GA" `
  --part-root "Core Algrithms/distributed_results/STRESS_NEW_PO" `
  --part-root "Core Algrithms/distributed_results/STRESS_NEW_GA_PO" `
  --output-root "Core Algrithms/distributed_results/STRESS_NEW_COMBINED"
```

Không dùng lệnh merge này để biến gói D155 thành worker_manifest giả của source
hiện tại. D155 là benchmark lịch sử đã hậu kiểm, được xuất bản byte-exact riêng.
Nếu bị ngắt/lỗi, kiểm nguyên nhân và chỉ resume khi được duyệt, không tự đổi
seed/data/budget rồi tái sử dụng kết quả cũ. Lần tích hợp này không commit/push.
