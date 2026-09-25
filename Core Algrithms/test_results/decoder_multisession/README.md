# Kiểm thử decoder nhiều buổi (fixture tổng hợp)

Chạy lại từ thư mục `Core Algrithms`:

```powershell
$env:PYTHONPATH = 'src'
python -m tests.run_decoder_multisession_experiment
```

Cần `matplotlib` để tạo PNG. Script dùng 40 seed `0..39` cho fixture stress 12 buổi/3 tuần, giới hạn node `12, 14, 16, 18, 24, 40`; cũng kiểm tra miền encoder đầy đủ và bốn quy mô `4, 12, 24, 60` buổi với 10 seed mỗi quy mô. Một lượt `SUCCESS` chỉ được ghi sau khi validator độc lập xác nhận lịch và vector đã đồng bộ với option được chọn.

- `decoder_trials.csv`: toàn bộ lượt chạy, trạng thái, node, backtrack và thời gian.
- `summary.json`: cấu hình, seed và thống kê tóm tắt.
- `decoder_stability.png`: tỷ lệ giải mã thành công theo ngân sách node, cùng node/backtrack theo seed.
- `decoder_scaling.png`: median và min–max thời gian theo số buổi.

Đây là dữ liệu tổng hợp dùng để bắt lỗi và nhận diện điểm nghẽn, **không phải dữ liệu HUIT, không phải benchmark GA/PO và không chứng minh hiệu năng trên toàn học kỳ**. Thời gian đo cục bộ phụ thuộc máy và tải nền; không dùng làm ngưỡng pass/fail của unit test.

Kết quả trong thư mục này phản ánh decoder hiện hành đã tối ưu so cặp theo ngày. Bản đo trước–sau và ảnh so sánh được giữ riêng tại `../decoder_optimization/`.
