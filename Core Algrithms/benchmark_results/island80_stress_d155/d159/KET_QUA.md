# D159 — Xác nhận code chính trùng ISLAND80 D155

Hoàn tất 3/3 run mới, seed1 đã chọn trước cho ba quy mô; N30/20vòng/cap630.
Tự khởi tạo Random(1), không nạp initial hoặc nghiệm tối ưu đã lưu.

| Bộ | Q_general mới = cũ | Q_lecturer mới = cũ | FE | Mốc hội tụ | Decode fail | Backtrack | Hard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small | 0.014953571429 | 0.348824711873 | 600 | 21/21 | 235 | 20 | 0 |
| medium | 0.052152080682 | 0.352085271748 | 599 | 21/21 | 250 | 433868 | 0 |
| large | 0.050275269461 | 0.320780066251 | 575 | 21/21 | 525 | 6717291 | 0 |

Cả3 đều bằng **chính xác**, không chỉ bằng các số làm tròn trong bảng:

- Quần thể ban đầu và SHA30vector.
- Mỗi vector/fitness/phenotype/components ở tất cả FE thực tế.
- Dense best-so-far trace và toàn bộ21mốc hội tụ.
- Best vector, option indices, fullfitness, entries và mapping/checksum.
- Mọi optimization metric trừ runtime. Runtime không thể yêu cầu bằng nhau.
- Hậu kiểm replay hard0/fullcoverage,0softquery; nguồn/config/data/reference SHA không đổi.

Đợt này chứng minh tích hợp tương đương trên3trường hợp nặng được kiểm, không phải
chạy lại toàn bộ120D155 hoặc bằng chứng ưu thế mới của lai. Không đổi thuật toán, seed,
budget hoặc dữ liệu để làm khớp; giữ nguyên toàn bộ kết quả cũ. Không SQL/commit/push/automation.

Bằng chứng: summary.json,independent_audit.json,checks/,runs/,details/,provenance.json.
Các khác biệt được phép: nhãn ISLAND80 lịch sử → GA_PO production,request_id,
hybrid_mechanism mới và thời gian. Chất lượng/lịch/vết tìm kiếm không khác.
