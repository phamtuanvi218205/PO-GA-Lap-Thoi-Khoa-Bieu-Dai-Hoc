# ISLAND80 — kết quả chính thức D155 và xác nhận tích hợp D159

Đồng bộ D160,01/11/2026. Đây là bản sao dữ liệu đã chạy, **không rerun optimizer**.

## Đọc ngay

- [Báo cáo và nhận xét D155](d155/NHAN_XET.md), [kết quả D155](d155/KET_QUA.md).
- [Small](d155/analysis/small_convergence.png), [Medium](d155/analysis/medium_convergence.png),
  [Large](d155/analysis/large_convergence.png), [thắng–thua](d155/analysis/paired_comparison.png).
- [CSV từng lượt](d155/analysis/raw_results.csv), [CSV tổng hợp](d155/analysis/summary.csv),
  [JSON cặp so sánh](d155/analysis/pairs.json), [hậu kiểm](d155/analysis/independent_audit.json).
- [D159 xác nhận production trùng](d159/KET_QUA.md), [audit độc lập D159](d159/independent_audit.json).

## Nhãn và phạm vi

| Nhãn gốc D155 | Vai trò |
| --- | --- |
| GA | GA thuần,30run |
| PO | PO thuần,30run |
| HYBRID50 | Lai trộn chung50/50 cũ,30run đối chứng, không phải production hiện tại |
| ISLAND80 | Lai hai quần thể24GA/6PO,30run; là cơ chế GA_PO production hiện tại |
| GREEDY_FIRST_FEASIBLE | Mốc riêng,3run, không kiểm định nhiều seed |

D155120optimizer+3Greedy dùng ba fixture tổng hợp liên quan Small12/Medium18/
Large24lớp,D60/90/120,seed1–10,N30/T20/cap630;30cohort initial dùng chung.
D159 là3run mới seed1 tự khởi tạo lại trên code chính,khớp1774FE và63mốc,
0hard/0softquery. Không gọiD159 là chạy lại toàn bộD155.

ISLAND80 cuối20vòng soGA16/0/14,PO17/0/13,HYBRID5015/0/15; commonFE soPO
13/0/17. Đây là lợi thế nhỏ ở một số tiêu chí, không phải ưu thế thống kê
hoặc thắng nhất quán mọi quy mô. Giữ nguyên cả hai cách đo và các hạn chế.

## Dữ liệu thô đầy đủ và tính toàn vẹn

`evidence/d155.zip`: toàn bộ file D155, trừ cachePython/temp; gồm123result,
123detail,123checkpoint,30initialJSON+30pickle,source gốc,logs,progress,
analysis,protocol,provenance,status. `evidence/d159.zip`: toàn bộD159 tương tự.
`evidence/d150_inputs.zip`: snapshots/configs/manifest/witnesses đầu vào D150.

ZIP là nén không mất dữ liệu để tránh gần1GB JSON lặp mapping; mọi file giải
nén phải có SHA khớp `manifest.json`. Các báo cáo/ảnh/CSV/JSON xem trực tiếp
ngoàiZIP cũng được sao chép **byte-exact**, không chỉnh số liệu. Dữ liệu gốc
trong test_results không bị xóa/đổi nhãn/ghi đè. ZIP có pickle tin cậy nội bộ
để bảo tồn bằng chứng; lệnh verify chỉ kiểm byte, **không unpickle hoặc chạy
source lưu trữ**. Source cũ được lưu để truy nguyên, không phải lệnh resume
chạy với production mới. Dùng suite hiện hành cho run mới được duyệt.

Kiểm tra toàn gói (không cần test_results gốc, không SQL/optimizer):

```powershell
python "Core Algrithms/tools/sync_selected_benchmark.py" --verify
```

Lệnh kiểm mọi memberSHA/ảnh/bản sao,123result-checkpoint links,30initialSHA,
120run đúng nhãn/seed/budget,3Greedy và D159exact. `sync_audit.json` là biên bản
đóng gói; không thay thế audit hard replay gốc D155 hoặc D159. Không khai báo
SHA production hiện tại như thể đó là source đã chạy D155.

Nguồn đã chọn và kết quả được đưa đi cùng repo; xem Git log/nhánh hiện hành
để xác định commit công bố, không lấy thời điểm đồng bộ làm thời điểm benchmark.

D161 đã dọn các thư mục thử nghiệm rời trong test_results vào Thùng rác theo
yêu cầu người dùng. Các file được chọn vẫn có đầy đủ trong gói này; công cụ
verify/replay có thể đọc trực tiếp ZIP, không cần khôi phục bản nghiên cứu rời.
