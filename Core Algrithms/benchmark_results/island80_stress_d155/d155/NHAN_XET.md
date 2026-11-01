# D155 — Kết quả kiểm chứng chính thức lai hai đảo GA–PO 80/20

## 1. Kết luận cần đọc trước

ISLAND80 đạt mục tiêu **nhỉnh hơn GA về số cặp thắng** trong đợt này:
16 thắng / 0 hòa / 14 thua sau 20 vòng; tại FE thực chung là 17/0/13.
Tuy nhiên, chưa chứng minh mạnh nhất toàn bộ: so PO là 17/0/13 cuối vòng
nhưng 13/0/17 tại FE chung; so lai cũ HYBRID50 là 15/0/15 ở cả hai cách đo.
Không được diễn đạt thành vượt trội ổn định hoặc vượt có ý nghĩa thống kê.

Small và Large có tín hiệu tốt, Medium là điểm yếu còn rõ. Theo đúng tiêu chí
người dùng “chỉ cần thắng nhẹ GA”, ứng viên có tín hiệu đạt; đây không phải
quyết định tự động thay production. Production vẫn D153 Priority + Placement
hard-only và lai 50/50. Chưa sửa web/DB, chưa commit/push, không mở thử nghiệm khác.

## 2. Thiết kế và kiểm định

- 120 optimizer run mới: GA/PO/HYBRID50/ISLAND80 × Small/Medium/Large × seed 1–10.
- 3 baseline Greedy, đúng một lượt mỗi bộ, không giả thành 10 seed độc lập.
- 30 cá thể; 20 vòng; trần 630 FE gồm 30 initial; retry 5; node 20.000; repair 3.
- D150 dữ liệu cố định: 12/18/24 lớp, 232/343/454 buổi, 60/90/120 gene.
- Mỗi case/seed dùng chung đúng 30 cá thể ban đầu, đối chiếu SHA và toàn bộ
  record initial. Không chọn lại seed hoặc tái sử dụng prefix pilot 10 vòng.
- Cơ chế hai đảo giữ nguyên byte-SHA D154: 24 GA/6 PO, cả hai cập nhật toàn
  chromosome, PO đủ bốn hành vi và nhận con hợp lệ dù tạm xấu hơn, best riêng.
  Trao đổi tối đa một phenotype mới mỗi hướng sau vòng 2/4/.../18; bảo vệ best;
  không ép tournament GA chọn nghiệm PO.
- Bắt đầu 14:12:59, hoàn tất báo cáo tự động 16:48:07 ngày 01/11/2026:
  khoảng **2 giờ 35 phút**. Đây là wall time song song toàn chiến dịch, không
  dùng để xếp hạng tốc độ từng thuật toán.
- 123 JSON kết quả và 123 checkpoint; 30 initial cohort. `analysis/final_audit.json`
  và kiểm tra riêng `postcheck/finish.py` / `analysis/independent_audit.json` xác minh
  lại bằng production PlacementDecoder, Validator và Fitness: đủ coverage,
  cùng vector/option index/entries/full fitness, 0 hard violations, 0 chấm mềm.
  Kiểm lại dense trace từng FE, 20 vòng, source/config/data checksum không đổi.
- Mã hậu kiểm nằm ngoài frozen source; không gọi optimizer, không chạy lại nghiệm.
- Trước chạy: 497 test đạt, 5 SQL opt-in skip (488 production + 9 research).

## 3. Thắng / hòa / thua ghép cặp

Ưu tiên từ điển Q_general rồi Q_lecturer, ngưỡng so sánh 1e-12. Hòa không tính
là thắng. Mỗi ô là số cặp của ISLAND80 so đối chứng cùng case/seed.

### Sau đúng 20 vòng

| Đối chứng | Small | Medium | Large | Tổng 30 cặp |
|---|---|---|---|---|
| GA | 6/0/4 | 3/0/7 | 7/0/3 | 16/0/14 |
| PO | 4/0/6 | 6/0/4 | 7/0/3 | 17/0/13 |
| HYBRID50 | 6/0/4 | 3/0/7 | 6/0/4 | 15/0/15 |

### Tại cùng FE thực tế của từng cặp

So tại min(FE thực hai run), lấy từ dense trace, không kéo dài đường sau khi dừng.

| Đối chứng | Small | Medium | Large | Tổng 30 cặp |
|---|---|---|---|---|
| GA | 6/0/4 | 3/0/7 | 8/0/2 | 17/0/13 |
| PO | 4/0/6 | 5/0/5 | 4/0/6 | 13/0/17 |
| HYBRID50 | 6/0/4 | 3/0/7 | 6/0/4 | 15/0/15 |

Khác biệt so PO cho thấy không thể chỉ dùng kết quả cuối 20 vòng để kết luận
bản lai khai thác mỗi FE tốt hơn. PO có nhiều decode failure nên dùng ít FE hơn
trong cùng 20 vòng. Cả cấu hình vòng/trần FE và FE dùng thực cần báo đồng thời.

## 4. Trung vị chất lượng (càng nhỏ càng tốt)

Mỗi ô là Q_general / Q_lecturer trung vị **riêng từng chỉ số**. Đây không nhất
thiết là hai Q của cùng một lịch; không thay thế bảng so sánh ghép cặp.

| Bộ | GA | PO | HYBRID50 | ISLAND80 |
|---|---|---|---|---|
| Small | 0.034087 / 0.300776 | 0.027939 / 0.317879 | 0.035002 / 0.324825 | 0.033153 / 0.319873 |
| Medium | 0.044376 / 0.351941 | 0.050770 / 0.340353 | 0.045757 / 0.329220 | 0.050974 / 0.348663 |
| Large | 0.058782 / 0.344289 | 0.059973 / 0.322839 | 0.063095 / 0.338491 | 0.054631 / 0.338704 |

ISLAND80 có Q_general trung vị thấp nhất ở Large, không thấp nhất Small/Medium.
Q_lecturer thấp nhất riêng lẻ không tự động thắng khi Q_general kém hơn.

## 5. Cùng một tập bốn phương pháp: xếp hạng và số lần tốt nhất

Mỗi cohort có bốn đối thủ cùng đề bài và initial, không cộng Q khác thang hoặc
chỉ bỏ đối thủ bất lợi để đếm. Không đưa Greedy vào xếp hạng nhiều seed.

| Phương pháp | Hạng trung bình cuối vòng | Đứng nhất / 30 | Pair wins / 90 cuối vòng | Pair wins / 90 FE chung |
|---|---:|---:|---:|---:|
| GA | 2.4 | 8 | 48 | 42 |
| PO | 2.6 | 8 | 42 | 50 |
| HYBRID50 | 2.6 | 5 | 42 | 43 |
| ISLAND80 | 2.4 | 9 | 48 | 45 |

ISLAND80 đứng nhất 9 cohort, nhiều nhất nhưng chỉ hơn GA/PO một cohort;
hạng trung bình và tổng pair wins cuối vòng bằng GA, còn FE chung PO nhiều
pair wins nhất. Không có một phương pháp thắng áp đảo ở mọi cách đo.

## 6. Hội tụ, độ phân tán và chi phí

| Phương pháp | Best cải thiện / 30 | Q_general cải thiện / 30 | Tổng FE thực | Candidate attempts | Decode fail | Backtracks |
|---|---:|---:|---:|---:|---:|---:|
| GA | 30 | 29 | 18,900 | 21,543 | 2,643 | 67,132,867 |
| PO | 30 | 30 | 12,886 | 52,012 | 39,126 | 149,882,493 |
| HYBRID50 | 29 | 29 | 16,032 | 35,717 | 19,685 | 85,852,199 |
| ISLAND80 | 30 | 30 | 17,717 | 27,513 | 9,796 | 80,045,399 |

FE đo Fitness của lịch hoàn chỉnh, không tính mỗi lần decode thất bại là một FE.
Số retry, repair và bước quay lui được giữ riêng. Do đó cùng trần 630 không có
nghĩa FE cuối bằng nhau hoặc thời gian tính toán bằng nhau. Không dùng CPU full
load/wall time chạy đồng thời làm bằng chứng thuật toán nào nhanh hơn.

Các đường Q_general đều có xu hướng giảm; bản lai 80/20 giảm Q_general ở
30/30 run. Không còn trường hợp cả đường hội tụ nằm ngang từ khởi tạo như
decoder mềm trên dữ liệu dễ. Tuy nhiên có plateau cục bộ, không nên hứa mỗi
vòng phải giảm. Population ban đầu có phân tán Q_general: độ lệch chuẩn theo
cohort Small 0.031059–0.040899; Medium 0.019933–0.029877;
Large 0.011246–0.018359.

Q_lecturer của best từ điển có thể tăng khi Q_general giảm. Đây không phải
best-so-far bị đánh mất: nghiệm có Q_general tốt hơn được ưu tiên trước.

## 7. Đóng góp thật của hai thuật toán trong ISLAND80

| Dấu vết (tổng 30 run) | GA | PO |
|---|---:|---:|
| Offspring slots | 14,400 | 3,600 |
| Con hợp lệ | 14,400 | 2,417 |
| Lần cải thiện global best có ý nghĩa (>1e-12) | 180 | 13 |
| Vector mới | 13,805 | 2,263 |
| Phenotype mới | 5,250 | 1,972 |

- PO nhận **1,179 con hợp lệ tạm xấu hơn cha**, tiếp tục tìm kiếm độc lập;
  không chỉ là mutation của con GA.
- GA → PO **265** migration; PO → GA **270** migration; trong đó **141**
  nghiệm PO tự phát hiện được gửi về GA.
- Tournament GA thực sự chọn vector PO tự phát hiện làm cha **573 lần**;
  không ép chọn để làm đẹp số liệu.
- Bốn hành vi PO đều được dùng; 9,740 lượt gọi công thức gồm các retry.
- GA đóng góp phần lớn global best gain. PO có đóng góp trực tiếp và gián tiếp
  được quan sát, nhưng không được quy mọi lợi ích là do công thức PO:
  không có RAND ablation chính thức đợt này; pilot RAND cuối vòng chỉ 3 thắng/3 thua.

## 8. Greedy và mức độ chứng cứ

Greedy tìm được lịch hợp lệ cả ba bộ; mỗi bộ một lịch:

| Bộ | Q_general | Q_lecturer | ISLAND80 so Greedy (10 seed so một mốc) |
|---|---:|---:|---|
| Small | 0.054688 | 0.298213 | 10 thắng / 0 hòa / 0 thua |
| Medium | 0.046612 | 0.304793 | 3 thắng / 0 hòa / 7 thua |
| Large | 0.061034 | 0.308170 | 7 thắng / 0 hòa / 3 thua |

Không được nói Greedy luôn kém xa: Medium Greedy cạnh tranh tốt và tốt hơn
7/10 lịch ISLAND80. Các phép so trên là mô tả một mốc deterministic,
không phải 10 baseline độc lập để làm kiểm định seed.

Exact sign test hai phía, loại hòa và Holm ba đối chứng cho mỗi endpoint:
tất cả p_Holm = 1.0. So GA cuối vòng p_raw = 0.855536; FE chung 0.584665.
Chưa có bằng chứng khác biệt thống kê; chỉ nhận xét xu hướng thắng nhẹ.
Các kiểm định là thăm dò vì đã thử nhiều cơ chế và các fixture có quan hệ mở rộng,
không phải ba trường độc lập hoặc holdout mù. Không chọn riêng Large để kết luận chung.

## 9. File để đọc và dùng báo cáo

- `KET_QUA.md`: bảng tự động từ saved JSON.
- `analysis/independent_audit.json`: hậu kiểm riêng, không optimizer rerun.
- `analysis/rows.json`, `pairs.json`, `summary.json`, `ranks.json`, `sign_tests.json`.
- `analysis/raw_results.csv`, `summary.csv`: số liệu bảng.
- `analysis/small_convergence.png`, `medium_convergence.png`, `large_convergence.png`:
  median/IQR 10 seed theo vòng và FE thực trong miền chung, không pad đuôi.
- `analysis/quality_distribution.png`, `paired_comparison.png`: chất lượng và cặp thắng/thua.
- `analysis/cooperation_contributions.png`, `search_cost_by_scale.png`, `quality_by_scale.png`.
- Ba ảnh `*_island80_timetable.png`: seed trung vị từ điển, không chọn lịch đẹp nhất;
  `*_timetable_source.json` ghi seed/quality đã chọn. Ảnh chỉ mô phỏng tuần 1;
  coverage toàn kỳ được kiểm tra trên toàn bộ entries, không suy từ ảnh một tuần.

Đã xem trực tiếp cả ba ảnh hội tụ, phân bố, paired và thời khóa biểu Medium.
Không sửa kết quả cũ, dữ liệu hay source đã frozen. Chờ người dùng quyết định
giữ ứng viên, đổi cơ chế hoặc tích hợp; không tự chạy thêm benchmark.
