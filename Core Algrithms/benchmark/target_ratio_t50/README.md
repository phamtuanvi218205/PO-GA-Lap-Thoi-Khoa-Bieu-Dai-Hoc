# Khảo sát tỷ lệ GA và PO trên cơ chế TARGET

Chỉ chuẩn bị bộ chạy; chưa chạy benchmark trên máy người dùng. Không sửa
production, Word, snapshot hay kết quả 80/20. Chưa có kết quả cho hai tỷ lệ mới.

## Thiết kế cố định

| Tỷ lệ GA/PO | Vị trí GA / PO mỗi vòng | Lượt mới |
|---|---|---|
|80/20|24/6|0; dùng 30 kết quả T50 đã lưu|
|70/30|21/9|30|
|60/40|18/12|30|

Small/Medium/Large × seed 1–10; N = 30, T = 50, trần 1.530 FE gồm 30 initial.
Dữ liệu hiện hành phân công riêng TeachingPart: 72/108/144 gene, 232/343/454 buổi.
Giới hạn 5 vector/vị trí, 20.000 node/lần Decoder, Repair 3 lần và cùng miền lựa chọn.
Tải đúng 30 cohort đã lưu, kiểm SHA; không tạo lại initial, không chạy GA/PO/Greedy
hay ablation. Chỉ truyền ga_ratio khác vào production TARGET; không sửa công
thức PO, chọn nhóm, phản hồi, quy tắc bộ nhớ, GA hoặc Decoder. Quần thể đầu cùng
30 nghiệm nhưng tỷ lệ chia sau hoán vị seed thay đổi đúng theo tỷ lệ. Tỷ lệ
không đồng nghĩa tỷ phần FE thành công hoặc thời gian tính toán.

Phải giữ tất cả quy mô/seed/tỷ lệ, kể cả kết quả bất lợi. So cuối 50 vòng và exact
common FE từng cặp. Median Qg/QL riêng theo scale; có FE/fail/backtrack và đóng góp.
Hai phép 80/20 vs 70/30 và 80/20 vs 60/40 cùng nhóm Holm2 thăm dò khi đủ hai phần;
70/30 vs 60/40 báo mô tả. Dữ liệu đã dùng phát triển nên chưa là xác nhận độc lập
của tỷ lệ được chọn sau khi xem kết quả. Không xếp hạng runtime các máy khác nhau.

## Chuyển sang máy khác

ZIP dựng bằng lệnh bundle dưới đây chứa mã nguồn cần thiết, bộ dữ liệu T50,
30 kết quả 80/20 và 30 initial, giao thức và notebook. Không có Word, ProjectContext,
ChangeLogs, .env, DB, thư mục kết quả khác. Chỉ giải nén gói tin do nhóm cung cấp,
không dùng pickle từ nguồn lạ. SHA kiểm tra tính toàn vẹn, không thay xác minh
người gửi. Không cần SQL Server/GPU/TPU để chạy bài này.

Python >= 3.11 (ưu tiên 3.12 giống máy gốc). Tại thư mục giải nén:

```bash
python -m pip install numpy matplotlib psutil
python "Core Algrithms/tools/run_target_ratio_t50.py" check
```

Lệnh check chỉ đọc nguồn/cấu hình/SHA/miền tĩnh; không gọi optimizer hay khởi tạo.
Có thể chuẩn bị thư mục đóng băng mà chưa chạy:

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" prepare --ratio GA70_PO30 --output-root "RATIO_T50_70_30"
```

## Chạy local trên một máy

Từ thư mục gốc repository, dùng Python >= 3.11 (ưu tiên 3.12), cài phụ thuộc và
kiểm tra trước. Lệnh check không chạy benchmark:

```bash
python -m pip install numpy matplotlib psutil
python "Core Algrithms/tools/run_target_ratio_t50.py" check
```

Chạy cả hai tỷ lệ, tổng 60 lượt mới, với một controller dùng chung giới hạn worker:

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" run --ratio ALL --output-root "Core Algrithms/test_results/RATIO_T50_70_30_60_40" --workers 0 --acknowledge-compute
```

`--workers 0` tự chọn theo CPU/affinity/quota; controller kiểm tra RAM trước khi
khởi chạy thêm worker. Không chạy hai controller riêng trên cùng máy để tránh
mỗi controller tự dùng toàn bộ CPU. Không cần chạy lại 80/20, GA, PO hoặc Greedy.
Lệnh trên bắt đầu tính toán ngay; tài liệu này không tự khởi chạy lệnh đó.

Nếu đã dừng hoặc đã dùng prepare tạo cùng thư mục, giữ đúng tỷ lệ và thêm
`--resume` vào lệnh run. Thư mục có kết quả không bị ghi đè. Khi đủ 60 lượt,
controller tự kiểm tra và tạo báo cáo so cả ba tỷ lệ; không cần merge nếu chạy ALL.

## Hai máy mỗi máy một tỷ lệ

**Chỉ chạy các lệnh sau trên môi trường đã chọn, không chạy trên laptop nếu
chưa muốn tính toán.** Cờ acknowledge-compute là chốt xác nhận khởi chạy.

Máy 1:

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" run --ratio GA70_PO30 --output-root "RATIO_T50_70_30" --acknowledge-compute
```

Máy 2:

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" run --ratio GA60_PO40 --output-root "RATIO_T50_60_40" --acknowledge-compute
```

Mặc định worker theo CPU khả dụng, affinity/quota cgroup v2 và RAM; không lấy
24 CPU hiển thị thành 24 worker nếu quota chỉ 4 CPU. Có thể thêm --workers 4,
runner vẫn chặn theo giới hạn. CPU host khác nhau không đảm bảo nhanh hơn laptop.

Một máy chạy cả 60 lượt: --ratio ALL và thư mục mới. Không cần sửa script.
Ctrl+C yêu cầu dừng worker, giữ checkpoint đã hoàn thành. Muốn tiếp tục dùng đúng
lệnh run và thêm --resume, giữ nguyên ratio/output. Một lượt đang dở sẽ chạy lại
từ initial; các lượt đã có checkpoint hợp lệ được bỏ qua. Không resume tại một
thế hệ giữa lượt. Nếu chuyển phần đang dở sang host khác và gặp lock host, phải
xác nhận controller cũ đã dừng trước xử lý lock; không xóa lock khi còn worker hoạt động.

Notebook miễn phí có thể bị thu hồi VM, trong đó disk tạm mất dù đã có checkpoint.
Cần sao lưu thư mục output sang lưu trữ bền vững. Save & Run All của Kaggle lưu
outputs khi hoàn tất; không coi đó là bảo đảm backup giữa một phiên bị hủy.
Nếu ước lượng một phần dài hơn phiên miễn phí, hãy dừng sạch, sao lưu, tiếp tục;
không đổi seed hoặc bỏ lượt chậm để làm đẹp kết quả.

## Kiểm và gộp

Mỗi máy gửi nguyên thư mục output đã COMPLETED, không chỉ runs/. Report từng phần
chỉ so với 80/20 và không ban hành Holm2 khi thiếu tỷ lệ còn lại.

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" merge --part-root "RATIO_T50_70_30" --part-root "RATIO_T50_60_40" --output-root "RATIO_T50_COMBINED"
```

Merge chỉ kiểm/gộp/replay best/sinh báo cáo và PNG từ JSON, không optimizer. Có
status.json, runs/details/checkpoints/progress/logs/analysis, KET_QUA.md.
Report chạy lại từ JSON nếu cần:

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" report --output-root "RATIO_T50_COMBINED"
```

Chuẩn bị gói nén mới (đường dẫn ZIP phải chưa tồn tại):

```bash
python "Core Algrithms/tools/run_target_ratio_t50.py" bundle --zip "outputs/TARGET_RATIO_T50_70_30_60_40.zip"
```

Nhãn và giao thức ở thư mục này là nghiên cứu riêng, chưa được gộp Word hoặc chọn
tỷ lệ production. Chưa có kết quả hoặc thời gian chạy đo được cho hai tỷ lệ mới.
