# Đối chiếu decoder trước và sau tối ưu

- `baseline/`: 320 ca được chạy **trước** khi sửa `decoder.py`.
- `optimized/`: cùng 320 ca, cùng seed/miền/giới hạn node, chạy **sau** khi lập chỉ mục các buổi đã gán theo ngày.
- `comparison/paired_trials.csv`: từng cặp thời gian đo.
- `comparison/comparison.json`: kiểm tra kết quả và median theo quy mô.
- `comparison/decoder_speedup.png`: ảnh so sánh tốc độ.

Chạy lại comparator từ thư mục `Core Algrithms`:

```powershell
python -m tests.compare_decoder_optimization
```

Comparator từ chối so sánh nếu khác seed, miền, ngân sách, trạng thái, option được chọn, vector sửa, node, backtrack hoặc lý do thất bại; chỉ thời gian được phép khác. Bản baseline được lưu từ code cũ trước khi sửa tại lượt làm việc này. Muốn tái đo baseline phải có lại đúng code decoder cũ; chạy script đo hiện tại trên cả hai thư mục sẽ không tái tạo so sánh trước–sau.

Đây là phép đo cục bộ trên fixture tổng hợp, **không phải benchmark hiệu năng HUIT hoặc chất lượng GA–PO**. Đặc biệt ở 4 buổi, mức chênh vài phần trăm rất nhỏ và có thể chịu ảnh hưởng nhiễu thời gian; không coi đây là kết luận tối ưu cho mọi quy mô.
