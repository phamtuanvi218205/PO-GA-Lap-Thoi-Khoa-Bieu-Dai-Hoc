# Kết quả benchmark thời khóa biểu đã chọn

**Bộ chạy mới cho đồng đội:** [ba ablation TARGET_PO80 — V3/T50](../benchmark_configs/target_po80_part_t50/ABLATION.md).
Gói tham chiếu tại đó kèm30kết quả FULL T50,detail/checkpoint và30initialcohort
đã hoàn tất trên LT/TH độc lập, dùng lại để chạy đối chứng; không phải D155
hoặc kết quả mới của ablation. Không cần chạy lại GA/PO/FULL/Greedy.

Ngày 05/11/2026, code chính chuyển sang TARGET_PO80. Gói dưới đây giữ nguyên
ISLAND80 lịch sử và các số liệu hiện có trong Word; không phải kết quả của cơ
chế mới. Nghiên cứu TARGET_PO80 được giữ riêng trong
`test_results/target_po80_d155_20261105/`; Word chưa cập nhật.

**Bản dùng trong báo cáo:** [ISLAND80 — D155](island80_stress_d155/README.md).

- [Nhận xét đầy đủ](island80_stress_d155/d155/NHAN_XET.md).
- [Bảng kết quả D155](island80_stress_d155/d155/KET_QUA.md).
- [Xác nhận code chính trùng D155 — D159](island80_stress_d155/d159/KET_QUA.md).
- [Kịch bản nặng TARGET_PO80 hiện hành](../benchmark_configs/target_po80_stress/README.md).
- [Kịch bản ISLAND80 đã đóng băng](../benchmark_configs/stress/README.md).

Gói giữ đủ120optimizer+3Greedy D155 và3run D159, báo cáo/ảnh/JSON/CSV gốc,
source/protocol/provenance,initial/records/checkpoints và inputsD150. Không phải
một benchmark mới, không chọn riêng kết quả đẹp, không thay nhãn phương pháp.
PHENO80 không phải cơ chế được chọn, không ghép vào bảng4method D155.

Các kết quả `distributed_results/`, `test_results/timetable_*` và benchmarkCEC
cũ vẫn được giữ làm lịch sử; chúng không thay thế bộ stressD155 được chọn.
