# Benchmark GA PO và ISLAND80 trên CEC 2022

## Phiên bản đồng bộ với ứng dụng

Điểm chạy hiện tại là `launch_production_cec.py`; launcher đóng băng source rồi
gọi controller `run_production_cec.py`. Ba phương pháp GA, PO và
ISLAND80 import toán tử từ `gapo_timetabling.core`; ISLAND80 giữ hai quần thể
24/6, archive PO6 và migration mỗi hai vòng. Chi tiết trong
`PRODUCTION_CEC_PROTOCOL.md`; adapter được đối chiếu toàn bộ quỹ đạo với vòng
lặp code chính trong `tests/test_production_algorithms.py`.

Chạy từ gốc repository, không cần sửa PYTHONPATH:

```powershell
python "Core Algrithms/benchmark/launch_production_cec.py" --output "Core Algrithms/benchmark/results/cec2022_island80_moi" --workers 14
```

Cấu hình đầy đủ gồm 12 hàm, D20, N30, 30 seed và 300.000 FE mỗi lượt:
1.080 lượt mới. Tọa độ tìm kiếm thuộc [0,1] như code chính; cổng đánh giá
chuyển x=-100+200u. CEC không có lịch; archive/migration phân biệt bằng vector
chính xác. Không chạy Encoder/Decoder hoặc đọc DB. Không nhập lại kết quả của
cơ chế lai khác. Lưu từng JSON run và trace nén, config/SHA, status và audit;
thư mục đã tồn tại chỉ được tiếp tục khi có `--resume` rõ ràng và cùng cấu hình.

Sau khi controller báo COMPLETED, kiểm tra độc lập và tạo báo cáo/ảnh từ kết
quả đã lưu (không chạy optimizer thêm):

```powershell
python "Core Algrithms/benchmark/audit_production_cec.py" "Core Algrithms/benchmark/results/cec2022_island80_moi"
python "Core Algrithms/benchmark/report_production_cec.py" "Core Algrithms/benchmark/results/cec2022_island80_moi"
```

## Phiên bản tái lập kết quả 50/50 trước đây

Các hướng dẫn `run_benchmark.py`, hai profile và các tham số 50/50 bên dưới
chỉ dành cho tái lập bộ kết quả cũ. Chúng không phải cấu hình ISLAND80 hiện tại.

Thư mục này chỉ đánh giá ba thuật toán trên bộ 12 hàm benchmark CEC 2022
chính thức trước khi đưa chúng vào bài toán xếp lịch. Benchmark không đọc cơ sở
dữ liệu và không sử dụng encoder/decoder thời khóa biểu.

## Nguyên tắc công bằng

- Ba thuật toán dùng cùng hàm, số chiều, miền tìm kiếm và kích thước quần thể.
- Với cùng một function và seed, ba thuật toán nhận bản sao của cùng quần thể
  ban đầu.
- Ngân sách được đo bằng FE (fitness evaluations), không chỉ bằng iteration.
- Cùng phép sửa biên `clip` được dùng sau khi sinh vị trí mới.
- Sai số được tính bằng `f_best - f*` vì optimum của CEC 2022 không đồng loạt
  bằng 0.
- Runner dừng nếu evaluator trả giá trị thấp hơn optimum vượt quá sai số làm
  tròn; không che lỗi adapter bằng cách âm thầm ép sai số âm về 0.

## Hai profile đều dùng CEC 2022

| Profile | Mục đích | Quy mô |
|---|---|---|
| `cec2022_pilot` | Kiểm tra kỹ thuật, ước lượng runtime; không dùng làm kết luận | 12 hàm, D=20, 3 seed, 30.000 FE |
| `cec2022` | Thực nghiệm chính | 12 hàm, D=20, 30 seed, 300.000 FE |

Profile `cec2022` gồm `12 × 3 × 30 = 1.080` lần chạy, tương ứng tối đa
324 triệu FE. Profile pilot chỉ dùng để bắt lỗi và kiểm tra đầu ra; không dùng
để chọn lại tham số trên chính 12 hàm sẽ báo cáo.

## Lệnh chạy

Mở terminal tại thư mục `Core Algrithms/benchmark`:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python run_benchmark.py --profile cec2022_pilot
python run_benchmark.py --profile cec2022
```

Có thể chỉ định thư mục kết quả:

```powershell
python run_benchmark.py --profile cec2022_pilot --output results/cec2022_pilot_moi
```

Full CEC có thể chia thành các shard seed độc lập. Mỗi shard phải ghi vào một
thư mục riêng; không cho nhiều process cùng ghi một CSV:

```powershell
python run_benchmark.py --profile cec2022 --seed-start 1 --seed-end 8 --output results/cec2022_shard_01_08
python merge_cec2022_shards.py --inputs results/cec2022_shard_01_08 ... --output results/cec2022_only_official_full
```

Khi shard chạy song song, runtime bị ảnh hưởng bởi tranh chấp CPU. File
`merge_metadata.json` ghi rõ giới hạn này; fitness và FE vẫn tái lập theo seed.

`config.json` lưu cả cấu hình thực nghiệm và dấu vết giao thức thuật toán.
Runner chỉ resume khi toàn bộ nội dung trùng khớp để không trộn kết quả cũ và
mới sau khi code, tham số hoặc survivor selection thay đổi.

## File kết quả

- `raw_results.csv`: một dòng cho mỗi function–algorithm–seed.
- `summary.csv`: best, worst, mean, median, standard deviation và runtime.
- `convergence.csv`: best error theo từng mốc FE.
- `ranks.csv`, `average_ranks.csv`: thứ hạng theo median của từng hàm.
- `statistical_tests.csv`: Friedman và Wilcoxon có hiệu chỉnh Holm.
- `01_convergence.png`: median và khoảng 25%–75% theo FE.
- `02_final_error_boxplots.png`: độ ổn định của sai số cuối.
- `03_rank_heatmap.png`: hạng 1, 2, 3 của từng thuật toán trên từng hàm.
- `04_runtime.png`: thời gian với cùng ngân sách FE.

## Tham số thuật toán

- GA: tournament size 3, SBX probability 0,9, SBX eta 15, polynomial mutation
  probability `1/D`, mutation eta 20 và elitism một cá thể.
- PO V2: `beta=1,5` và bốn công thức hành vi theo mã tham chiếu của tác giả.
- GA–PO: `p=0,5`; mỗi thế hệ chia quần thể thành hai nhóm, hợp
  `P(t) ∪ A' ∪ B'`, giữ N cá thể tốt nhất rồi xáo trộn.

CEC 2022 được đánh giá bằng source C++ chính thức đã cố định commit và SHA-256.
Lần chạy đầu tiên sẽ tải source vào `.cache/cec2022_official` và biên dịch DLL
cục bộ; Windows cần Microsoft C++ Build Tools. Nguồn chính thức:
https://github.com/P-N-Suganthan/2022-SO-BO
