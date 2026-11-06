# Chỉ chạy ba thí nghiệm thành phần — không chạy lại ba thuật toán chính

GA, PO và TARGET_PO80 đầy đủ trên mô hình LT/TH độc lập,50vòng đã chạy xong.
Lần này **chỉ có90lượt ablation mới**, không thêm lượt GA/PO/FULL/Greedy.

| Mã dùng trong lệnh | Thay đổi duy nhất so với lai đầy đủ | Lượt mới |
|---|---|---:|
|`TARGET_RAND80`|Thay giá trị do công thức PO tạo trên mặt nạ bằng khóa uniform[0,1); giữ cách chọn nhóm, bộ nhớ và phản hồi.|30|
|`NO_FEEDBACK`|Tắt đưa ứng viên PO vào chọn lọc survivorGA; giữ anchorGA→PO, bộ nhớPO và best chung.|30|
|`RANDOM_GROUP`|Chọn danh tính nhóm ngẫu nhiên, giữ loại/kích thước mặt nạ; vẫn dùng công thứcPO và phản hồi.|30|

Mỗi biến thể chạy Small/Medium/Large×seed1–10, N30/T50/cap1530 gồm30initial,
retry5/node20k/repair3/init30k;24slotGA/6slotPO. Không thay tỷ lệ, dữ liệu,
Decoder, Repair, Validator hoặc Fitness để ưu tiên một biến thể.

`RANDOM_GROUP` vẫn dùng tiêu chí trội để quyết định loại/kích thước nhóm;
không gọi nó là đã bỏ toàn bộ hướng dẫn mục tiêu. `NO_FEEDBACK` chỉ bỏ chiều
PO→GA, không phải tắt mọi trao đổi hoặc tắt di trú của cơ chế ISLAND80 cũ.

## Dữ liệu và bằng chứng kèm theo

- `data/*.json`: ba snapshotV3 byteexact của bộ50vòng đã hoàn tất,
  D72/108/144,232/343/454buổi, LT/TH có thể khác người.
- `references/full_t50_reference.zip`: **30kết quả FULL đã hoàn tất**, đủ
  detail/denseFE/checkpoint và30cohort khởi tạo gốc (JSON+pickle), không có
  kết quả ablation mới giả lập hoặc kết quả SECTION cũ.
- Manifest khóa SHA của archive và đủ150entry. Chỉ sau kiểmSHA mới giải nén
  và đọc pickle do dự án tự tạo; không dùng pickle không rõ nguồn gốc.
- Package49file Python được khóa SHA chuẩn hóaCRLF→LF trong `protocol.json`;
  adapter ablation nằm riêng ngoài production/web. Mỗi output chụp lại toàn
  bộ source/config/input/cohort và fingerprint trước khi chạy.
- Kết quả FULL được đọc lại để đối chiếu cuối50vòng và exactcommonFE;
  không khởi chạy optimizerFULL hoặc ghép thêm vòng vào kết quả cũ.

## 1. Cài đặt và kiểm tra

Checkout cùng commit của nhánh `codex/complete-demo-benchmark-results` trên
mọi máy. Mở terminal tại thư mục gốc repository rồi chạy:

```text
python -m pip install -e ".[dev]"
python "Core Algrithms/tools/run_target_ablation_t50.py" check
```

Hai lệnh dùng được trong PowerShell/CMD/Git Bash/Linux; không cần đặt
PYTHONPATH hoặc kết nối SQL Server. Nếu Git Bash không có lệnh `python`, dùng
Python đã cài trong máy, chẳng hạn `py -3.11`. `check` chỉ đọc/kiểm file,
không chạy optimizer. Không đổi code/config sau khi đã bắt đầu đợt chạy.

## 2. Một máy chạy cả ba ablation (90lượt mới)

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" run --output-root "Core Algrithms/test_results/ABLATION_T50_team01" --workers 16
```

Đổi `16` theo CPU được cấp thực tế. Bỏ `--workers` để tự chọn theo CPU logic/
affinity và quota cgroupv2 khi có. Controller còn giới hạn số job theo RAM
khả dụng. Mỗi job optimizer vẫn tuần tự, không đổi RNG theo thứ tự hoàn tất;
không dùng runtime các job song song để xếp hạng thuật toán.

## 3. Hoặc chia ba biến thể cho ba máy

Máy1 — chỉ thay công thức bằng ngẫu nhiên:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" run --variant TARGET_RAND80 --output-root "Core Algrithms/test_results/ABLATION_T50_team01_RAND" --workers 16
```

Máy2 — chỉ tắt phản hồi PO→GA:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" run --variant NO_FEEDBACK --output-root "Core Algrithms/test_results/ABLATION_T50_team01_NO_FEEDBACK" --workers 16
```

Máy3 — chỉ chọn nhóm ngẫu nhiên cùng footprint:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" run --variant RANDOM_GROUP --output-root "Core Algrithms/test_results/ABLATION_T50_team01_RANDOM_GROUP" --workers 16
```

Mỗi lệnh trên chỉ30lượt, không chạy lại FULL/GA/PO/Greedy. Gửi nguyên output
cho máy tổng hợp, giữ `manifest.json`, `status.json`, source, checkpoint và
JSON gốc. Output có dữ liệu nguồn/initial giống nhau do sao từ cùng archive.
Đặt ba output trên máy tổng hợp rồi dùng **thư mục merge mới**:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" merge --part-root "Core Algrithms/test_results/ABLATION_T50_team01_RAND" --part-root "Core Algrithms/test_results/ABLATION_T50_team01_NO_FEEDBACK" --part-root "Core Algrithms/test_results/ABLATION_T50_team01_RANDOM_GROUP" --output-root "Core Algrithms/test_results/ABLATION_T50_team01_COMBINED"
```

Merge chỉ nhận phần đã COMPLETED,cùng fingerprint source/protocol/reference;
không chạy optimizer, không ghi đè kết quả mâu thuẫn. Báo cáo đủ ba đối chứng
mới dùng Holm3; báo cáo của một phần riêng không thay thế báo cáo kết hợp.

## 4. Nếu máy hoặc terminal bị ngắt

Lưu output trên ổ bền vững. Với notebook đám mây, ổ tạm có thể bị xóa khi phiên
hết hạn; việc hỗ trợ cloud sync không nằm trong launcher này. Không đưa máy
vào Sleep trong khi muốn benchmark tiếp tục chạy.

Chạy lại đúng lệnh, cùng lựa chọn biến thể/output-root, thêm `--resume`:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" run --output-root "Core Algrithms/test_results/ABLATION_T50_team01" --workers 16 --resume
```

Chỉ lượt đã có checkpoint hợp lệ mới được bỏ qua. Lượt đang dở bắt đầu lại
từ cohort gốc, không tiếp tục giữa vòng; các tệp dở đã ghi được chuyển vào
`incomplete/`,không xóa. Log mỗi lần thử được lưu riêng. Không khởi chạy hai
controller cùng output-root; không tự restart sau lỗi hoặc đổi seed/budget.

## 5. Khi hoàn tất

Chỉ COMPLETED sau đủ số lượt được giao và hậu kiểm replaybest. Xem:

- `status.json`, `progress/*.json`, `logs/`;
- `KET_QUA.md`, `analysis/summary.json`, `pairs.json`, `quality_summary.json`,
  `sign_tests.json`, `final_audit.json`;
- ba ảnh hội tụ và `paired_comparison.png` từ JSON đã lưu.

Nếu optimizer đã đủ nhưng chỉ báo cáo lỗi, có thể chạy lại hậu xử lý:

```text
python "Core Algrithms/tools/run_target_ablation_t50.py" report --output-root "Core Algrithms/test_results/ABLATION_T50_team01"
```

Lệnh `report` không chạy optimizer. Báo mọi seed, cả kết quả bất lợi; kiểmđịnh
là thăm dò trên fixture liên quan, đã dùng phát triển phương pháp. Kết quả
ablation mới chưa được tự đưa vào Word, production hoặc đổi kết quả cũ.
