# GA–PO Timetabling — Python runtime

## Bàn giao mới nhất — chỉ chạy ba ablation T50 (06/11/2026)

Code chính hiện dùng TARGET_PO80 và LT/TH độc lập theo TeachingPart. Bộ ba
thuật toán GA/PO/lai đầy đủ trên mô hình mới,50vòng đã chạy xong. Lần bàn giao
này **chỉ chạy90lượt ablation**: `TARGET_RAND80`, `NO_FEEDBACK`, `RANDOM_GROUP`.
Không chạy lại GA, PO, FULL hoặc Greedy. Dùng đúng hướng dẫn:

**[Lệnh cho đồng đội và dữ liệu tham chiếu T50](benchmark_configs/target_po80_part_t50/ABLATION.md)**.

Tại thư mục gốc repo (PowerShell, CMD, Git Bash hoặc Linux):

```text
python -m pip install -e ".[dev]"
python "Core Algrithms/tools/run_target_ablation_t50.py" check
python "Core Algrithms/tools/run_target_ablation_t50.py" run --output-root "Core Algrithms/test_results/ABLATION_T50_team01" --workers 16
```

`check` không chạy optimizer. Lệnh `run` trên chỉ ba ablation; điều chỉnh số
worker theo máy. Có lệnh chia từng ablation cho ba máy, merge và resume trong
hướng dẫn. Gói reference kèm đủ30FULL T50 và30cohort đã lưu, khóaSHA, không
phụ thuộc thư mục nghiên cứu riêng hoặc database. Các bộ20vòng/SECTION phía
dưới là lịch sử, không dùng làm đầu vào của lượt ablation mới.

Mã nguồn Python được chia thành hai phần rõ ràng:

```text
src/gapo_timetabling/
├── core/          # Encoder, decoder, fitness, GA, PO và GA–PO
├── application/   # Database, plan, scenario, snapshot, báo cáo và chạy demo
├── __main__.py    # Điểm vào python -m gapo_timetabling
└── __init__.py
```

`core` là phần thuật toán thuần, không kết nối database. `application` thay thế
toàn bộ vai trò của ứng dụng Java cũ và gọi `core` để tối ưu.

## Biểu diễn và giải mã hiện hành

Từ 05/11/2026, snapshot tạo mới dùng `problem-instance.v3`, phân công theo
từng phần giảng dạy và biểu diễn `RECURRING_PRIORITY_PLACEMENT_PART.v1`:

- Mỗi phần giảng dạy có một gene giảng viên, xét năng lực LT hoặc TH tương ứng.
  LT và TH có thể cùng hoặc khác người. Các buổi của cùng một phần vẫn dùng
  chung người dạy trong cả kỳ; tải và độ phù hợp được tính theo người dạy thực.
- Mỗi khối buổi lặp có PriorityKey quyết định **thứ tự xếp**. Sắp tăng dần,
  bằng khóa thì theo ClassSession ID nhỏ nhất trong khối; không dùng MRV.
- Khóa PlacementKey riêng chọn hạng `min(floor(key*m), m-1)` trong **m mẫu
  hiện khả thi**, sau khi sắp thứ → tiết bắt đầu → phòng → index miền. Đây
  không phải chọn từ miền option tĩnh như biểu diễn cũ. Nếu bị kẹt, quay lui
  thử hạng gần nhất (k, k+1, k-1, ...), chỉ phục hồi hard feasibility trong
  ngân sách node. Không chấm mềm; Fitness đánh giá sau khi có lịch đầy đủ.
- Tổng số chiều là `P + 2B`: P gene giảng viên theo phần, B PriorityKey, B PlacementKey.
  Repair giữ chính sách đã thử: chỉ đổi giảng viên/priority, giữ placement.
- Mẫu được chọn vẫn cố định thứ–tiết–phòng trong mọi tuần hoạt động. Gene
  priority không bị viết lại thành chỉ số option; full Validator/Fitness cuối
  và các công thức GA/PO giữ nguyên. Cơ chế lai hiện hành được mô tả bên dưới.
- Mapping mới là `gene-option-mapping.v6`. Result JSON ghi `solver_pipeline`
  và `best_solution.vector_encoding` để replay đúng nghĩa vector.
- Snapshot v1/v2 giữ phạm vi SECTION và nhãn vector đã lưu, không tự đổi
  phân công sang từng phần; các kết quả đó không phải benchmark mô hình v3.
- Kết quả lịch sử L+B vẫn đọc đúng nhãn DIRECT_OPTION, FEASIBILITY.v1 hoặc
  SOFT.v1, không tự thêm PlacementKey. Thiếu nhãn là DIRECT_OPTION. Chỉ dùng
  các nhánh này cho replay; không đổi nhãn hay ghi đè kết quả cũ.
- Không tiếp tục benchmark mới vào thư mục DIRECT cũ hoặc hợp nhất worker
  khác pipeline. Dùng thư mục kết quả mới; không xóa hay đổi nhãn kết quả cũ.
  Run chờ lưu từ pipeline cũ được báo không thể phục hồi và cần tạo run mới.

## Cơ chế lai hiện hành — TARGET_PO80 (05/11/2026)

Người dùng đã duyệt áp dụng `TARGET_PO80` cho các lượt `GA_PO` mới:

- Mặc định 80% vị trí GA / 20% bộ nhớ tìm kiếm PO (N30 là24/6). GA dùng
  tournament, SBX, mutation và survivor selection sẵn có trên toàn chromosome.
- Sau nhánh GA, lấy6 lịch GA tốt nhất làm anchor. Thành phần phạt có đóng góp
  lớn nhất chọn tối đa2 đơn vị phân công hoặc2 khối; với v3, đơn vị phân công
  là TeachingPart. Trường hợp Qg bằng0 dùng thông tin Ql.
  PO cập nhật các tọa độ trong nhóm bằng đủ bốn công thức gốc. Gene ngoài nhóm
  giữ nguyên khi đề xuất; Decoder/Repair toàn cục vẫn có thể làm đổi lịch ngoài nhóm.
- Bộ nhớ6 giữ con hợp lệ dù kém anchor; mean lấy từ bộ nhớ đầu vòng, guide từ
  GA và bộ nhớ đó. Con tốt hơn anchor được đưa vào cạnh tranh survivor GA.
  Best toàn cục được bảo toàn riêng. Không còn di trú chu kỳ/archive của ISLAND80.
- Hai nhánh dùng chung FE, retry, Decoder/Repair/Validator/Fitness. T không còn
  bị gắn cứng20: lấy từ ngân sách và cỡ quần thể đã cấu hình. Cấu hình N30/T20
  được kiểm đối chiếu với mã nghiên cứu đóng băng; cấu hình khác cần đánh giá riêng.
- Result/request-config mang `hybrid_mechanism=GA_PO_TARGET_PO80.v1`; kết quả
  mới có dấu vết `hybrid_activity`. `injected` đếm con tốt hơn anchor được đề cử
  cho survivor GA, không đồng nghĩa tất cả đều sống sót. Job PENDING cơ chế cũ
  bị từ chối phục hồi để tránh đổi nghĩa thí nghiệm; lịch COMPLETED cũ giữ nguyên.
- Web vẫn dùng giải mã song song có thứ tự, cùng RNG/FE và kết quả như đường
  tuần tự. Không monkeypatch trong tiến trình API dùng chung.

Nguồn nghiên cứu: `test_results/target_po80_d155_20261105/`; ablation tại
`test_results/target_ablation_d155_20261105/`. Trên D155 đã dùng phát triển phương
pháp, bản mới thắng GA24/30, PO24/30, ISLAND80 28/30 cuối20vòng, nhưng thua đối
chứng thay công thức PO bằng ngẫu nhiên19/30. Hai ablation mới thuận lợi cho
phản hồi PO→GA và chọn nhóm theo mức phạt; chưa chứng minh công thức PO tốt hơn
ngẫu nhiên hoặc ưu thế tổng quát. Không đổi số liệu/nhãn kết quả lịch sử.

ISLAND80 được giữ tại `run_island_hybrid` để hồi quy và đối chiếu D155. Gói
`benchmark_results/island80_stress_d155/` vẫn là bằng chứng của ISLAND80 cũ,
không phải kết quả TARGET_PO80. Word chưa cập nhật theo quyết định này.

Bộ cấu hình hiện hành V3/T50 là `benchmark_configs/target_po80_part_t50/`;
ba snapshot D72/108/144 và lệnh ablation đã đóng gói ở đó. Bộ cấu hình
`benchmark_configs/target_po80_stress/README.md` vẫn dùng snapshot v2
D150, D60/90/120. Chưa chuyển bộ này sang benchmark LT/TH độc lập; cần snapshot v3
và quần thể đầu mới trước khi đánh giá mô hình mới. Bộ `benchmark_configs/distributed/` cũ giữ làm lịch sử, không
ghi đè. D155 vẫn là bằng chứng đo trên bốn phương pháp cũ; không sửa kết quả sau
tích hợp. ISLAND80 thắng cặp cuối run GA16/14, PO17/13, không phải ưu thế thống kê
hoặc thắng ở mọi cách đo. Không tự chạy thêm benchmark khi tích hợp.

Luồng chạy chính:

1. đọc dữ liệu rời rạc từ SQL Server;
2. sinh `TeachingPlan` và mở rộng thành `ClassSession`;
3. tạo, kiểm tra và khóa `PlanningScenario`;
4. dựng snapshot `problem-instance.v3`, phân công theo TeachingPart;
5. encoder sinh miền lựa chọn;
6. GA, PO hoặc GA–PO tối ưu phân công giảng viên và lịch;
7. lưu `OptimizationRun` cùng `TimetableEntry` vào database;
8. `TimetableQueryService` đọc run hoàn thành và gom occurrence tuần thành
   các mẫu lịch lặp; truy vấn có thể lọc theo giảng viên, lớp học phần, học kỳ
   và tuần.
9. `TimetableExportService` và `TimetableExcelExportService` xuất đúng dữ liệu
   đã lưu thành CSV UTF-8 hoặc workbook Excel `.xlsx`; bước xuất không chạy
   lại thuật toán và không ghi database.
10. FastAPI cung cấp API tra cứu, tải CSV/XLSX và đưa optimization run vào hàng
    đợi nền. Progress được đo bằng FE thật; timeout và hủy được kiểm tra tại
    checkpoint an toàn trong cả khởi tạo quần thể lẫn vòng lặp optimizer.
11. Dữ liệu nguồn của học kỳ có thể được nhập tay bằng JSON hoặc nhập hàng
    loạt bằng workbook `.xlsx`. Cả hai kênh cùng tạo `SemesterInputBundle`,
    dùng chung validator và được ghi trong một transaction SQL Server.
12. `SemesterReadinessService` kiểm tra dữ liệu nguồn mà không ghi database;
    `SemesterPreparationService` sau đó tự sinh plan/session, tạo hoặc tái sử
    dụng scenario, dựng snapshot và chạy encoder preflight. Endpoint này chưa
    khởi chạy GA, PO hoặc GA–PO.

## Cài đặt

```powershell
python -m pip install -e ".[dev]"
```

Khai báo `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` và tùy chọn
`DB_ODBC_DRIVER` theo file `.env.example`. Nếu không khai báo driver, runtime
tự ưu tiên ODBC Driver 18, sau đó Driver 17 và driver SQL Server có sẵn.

## Các lệnh chính

### CPU đa tiến trình cho demo

Các lượt chạy qua database/web tự dùng `application/parallel_execution.py` để
giải mã ứng viên bằng nhiều process. Mặc định `GAPO_EVALUATION_WORKERS=auto`:
tối đa 8 evaluator, theo CPU và RAM khả dụng, chừa 1 GiB RAM. Bài toán dưới
100 buổi dùng tuần tự để tránh phí khởi động process. Có thể đặt biến môi trường
`GAPO_EVALUATION_WORKERS=1` trước khi mở ứng dụng để dùng đường tuần tự; đặt số
khác để giới hạn evaluator (vẫn bị chặn theo CPU/RAM). `--run-workers` chỉ là số
lượt tối ưu đồng thời, không phải số lõi cho một lượt.

Optimizer, công thức, seed, thứ tự RNG và FE giữ nguyên: process phụ chỉ
Decoder/Repair/Validator, coordinator chỉ gọi Fitness cho ứng viên mà thuật toán
tuần tự thực sự dùng. Có giải mã dự đoán trước có thể bị bỏ; công này không
tăng FE nhưng vẫn tiêu CPU và được ghi riêng trong metadata `execution` của
kết quả trả về và log ứng dụng. Metrics optimizer chỉ tính các ứng viên đã dùng,
không phải tổng công vật lý gồm mọi suy đoán. Không dùng chế độ này để so runtime
với benchmark tuần tự. Đoạn PO cập nhật best phụ thuộc cá thể trước vẫn tuần tự;
chỉ những lần thử lại của cùng cá thể được giải mã trước. Không hứa tăng tốc
tuyến tính theo số lõi. Công cụ benchmark/CLI JSON vẫn dùng đường core cũ.

SQL chỉ chạy ở tiến trình API, không truyền kết nối vào worker. Hủy/timeout dừng
coordinator và các process tính toán. Không tự restart ứng dụng đang chạy hoặc
rerun kết quả cũ. Sau khi cập nhật code, kết thúc lượt demo hiện tại rồi khởi động
lại server và tải lại trang để dùng bản mới.

### Mở demo bằng một lần bấm (Windows)

Bấm đúp `CHAY_UNG_DUNG.cmd` ở thư mục gốc dự án. File tự tìm Python 3.11+
có các thư viện cần thiết, chạy cùng lệnh `serve-api` hiện hành và mở trình
duyệt tại `http://127.0.0.1:8000` khi API sẵn sàng. Giữ cửa sổ dòng lệnh
trong khi dùng, nhấn `Ctrl+C` để dừng server. Đóng tab trình duyệt không dừng server.

Nếu API đã chạy trên cổng 8000, file chỉ mở lại trang; không chạy thêm server.
Nếu cổng thuộc ứng dụng khác, file báo lỗi và không tự tắt tiến trình đó.
Launcher dùng cấu hình SQL mặc định/biến môi trường hiện có, không tự cài
Python/thư viện, không chạy migration, reset dữ liệu hoặc benchmark. Máy vẫn
cần SQL Server và ODBC driver như khi chạy bằng lệnh. Cơ chế khôi phục job
của ứng dụng khi khởi động vẫn giữ nguyên; mở ứng dụng có thể tiếp tục xử lý
các job còn chờ theo cơ chế sẵn có. Launcher không tự nạp file `.env`.

Chỉ kiểm tra môi trường, không chạy server: `CHAY_UNG_DUNG.cmd --check`.
Giữ file CMD và `Script/start_demo.py` trong cấu trúc dự án; có thể tạo shortcut
tới file CMD trên Desktop, không chuyển riêng file CMD ra khỏi dự án.

```powershell
python -m gapo_timetabling generate-plans 1
python -m gapo_timetabling create-scenarios 2026_HK1 --scope FULL_TERM
python -m gapo_timetabling build-snapshot 1 --output snapshot.json
python -m gapo_timetabling optimize 1 --algorithm GA_PO --population-size 60 --max-fe 30060 --seed 42
python -m gapo_timetabling export-schedule 1 --output timetable.csv
python -m gapo_timetabling export-schedule-xlsx 1 --output timetable.xlsx
python -m gapo_timetabling serve-api --host 127.0.0.1 --port 8000
```

Hai lệnh xuất lịch có thể nhận thêm `--lecturer-code`, `--section-code`,
`--term-code` và `--week-number`. Tệp CSV có BOM nên có thể mở trực tiếp bằng
Microsoft Excel mà không lỗi tiếng Việt. Workbook Excel gồm trang thời khóa
biểu và trang ghi lại run/bộ lọc đã dùng.

Sau khi chạy `serve-api`, tài liệu tương tác nằm tại
`http://127.0.0.1:8000/docs`. Các endpoint chính:

```text
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/schedule
GET  /api/runs/{run_id}/schedule.csv
GET  /api/runs/{run_id}/schedule.xlsx
POST /api/scenarios/{scenario_id}/optimization-jobs
GET  /api/optimization-jobs/{job_id}
POST /api/optimization-jobs/{job_id}/cancel
GET  /api/input-data/excel-template
GET  /api/input-data/terms
GET  /api/input-data/terms/{term_code}
POST /api/input-data/validate
POST /api/input-data/apply
POST /api/input-data/excel/preview
POST /api/input-data/excel/apply
GET  /api/input-data/terms/{term_code}/readiness
POST /api/input-data/terms/{term_code}/prepare
```

Workbook nhập liệu gồm các sheet học kỳ, cơ sở, môn, giảng viên, năng lực
giảng dạy, phòng/lớp trực tuyến, thiết bị, lớp học phần, cấu trúc môn học và lịch
khả dụng. Endpoint `preview` không ghi database. Endpoint `apply` chỉ ghi sau
khi toàn bộ workbook hợp lệ; lỗi giữa chừng làm rollback toàn bộ transaction.
Học kỳ đã có scenario `LOCKED` không được sửa dữ liệu nguồn. Workbook không
chứa TeachingPlan, ClassSession, option hoặc thời khóa biểu kết quả vì các dữ
liệu đó do pipeline tự sinh.

Endpoint `readiness` chỉ đọc và trả lỗi/cảnh báo có mã cùng đối tượng liên
quan. Endpoint `prepare` chỉ chạy khi readiness không còn lỗi; nó tự sinh dữ
liệu dẫn xuất, khóa scenario và xác nhận snapshot có miền gene dùng được. Nếu
encoder phát hiện scenario không có option, scenario đó được chuyển
`ARCHIVED` thay vì đưa sang optimizer. Gọi lại `prepare` sẽ tái sử dụng
scenario `LOCKED` hiện có để không tạo lặp cùng một đề bài. Snapshot và mapping
đầy đủ chỉ được lưu bất biến trong `OptimizationRun` khi người dùng thực sự
yêu cầu chạy thuật toán.

Mỗi yêu cầu chạy được tạo thành một `OptimizationRun` trạng thái `PENDING`
trước khi dựng snapshot. Vì vậy lỗi chuẩn bị, progress, yêu cầu hủy và trạng
thái cuối đều có bản ghi SQL Server. Job dùng định danh `run-{run_id}`; API có
thể tra cứu/hủy lại từ database sau restart. Khi dịch vụ khởi động, run
`PENDING` được đưa lại vào hàng đợi, còn run bị ngắt ở `RUNNING` được chạy lại
từ đầu với đúng snapshot/checksum đã lưu, cấu hình và seed. Đây là khởi động lại xác
định, không phải tiếp tục từ quần thể giữa chừng.

`serve-api --http-workers M --run-workers N` điều chỉnh số Uvicorn process và
số run tối đa trong mỗi process. `GAPO_RUN_WORKERS` có thể đặt qua môi trường;
mặc định mỗi process có 2 optimizer worker. SQL Server lưu `worker_id` và lease;
chỉ process claim thành công mới chạy một run. Process khác vẫn đọc/hủy được và
chỉ nhận lại run khi lease của worker cũ đã hết hạn. Hai biến tùy chọn
`GAPO_RUN_LEASE_SECONDS` và `GAPO_RUN_RECOVERY_INTERVAL_SECONDS` điều chỉnh
lease cùng chu kỳ quét. Khi tăng đồng thời M và N phải tính tài nguyên CPU/RAM.

`--max-fe` phải bao gồm chi phí khởi tạo quần thể và phần còn lại phải chia
hết cho `--population-size`, đúng hợp đồng FE dùng chung của ba optimizer.

## Nhập tay, cấu hình và điều chỉnh lịch

Database đang tồn tại cần chạy một lần
`Script/migrate_2026_10_28_complete_demo_workflow.sql` bằng SQL Server trước
khi mở giao diện mới. Migration không xóa run hoặc lịch gốc; nên sao lưu
database trước khi áp dụng. Schema tạo mới trong `Script/script.sql` đã có
hai bảng revision, không cần tạo thêm schema song song.

Trang Dữ liệu có biểu mẫu nhập tay theo nhóm: học kỳ, môn, giảng viên, năng
lực, phòng, lớp mở, cấu trúc môn, thiết bị và availability. Các nhãn tiếng Việt
được ánh xạ vào cùng `SemesterInputBundle` như Excel. Nút Đồng ý trong hộp
nhập chỉ sửa gói trên trình duyệt; Kiểm tra và Lưu dữ liệu mới gọi API.
“Bỏ khỏi gói” không xóa bản ghi đã lưu. Ngừng mở một lớp bằng trạng thái
`CANCELLED`, ngừng dùng tài nguyên bằng `is_active=false`. JSON nâng cao được
giữ trong mục thu gọn, không phải cách nhập tay bắt buộc.

Giao diện demo chỉ có bốn trang: Dữ liệu, Chuẩn bị, Thuật toán và Thời khóa biểu.
Đã bỏ hẳn tab/trang Ràng buộc, không chỉ ẩn các ô nhập trọng số/ngưỡng hoặc
nút Lưu. Người dùng không cần biết hệ số Fitness để chạy xếp lịch. Các ràng
buộc vẫn được áp dụng bên trong hệ thống, không bị xóa khỏi thuật toán.
Điểm mềm dùng để xếp hạng lịch hợp lệ, không phải điểm đích phải đạt mới dừng.

Cấu hình đang lưu, Fitness và hard constraints giữ nguyên. API kỹ thuật
`GET/PUT /api/constraint-settings` vẫn được giữ để tương thích, nhưng không
được giao diện demo gọi. Nếu điều chỉnh qua API, vẫn kiểm đủ sáu tiêu chí,
tổng trọng số mỗi tầng bằng1, ngưỡng nguyên1–16 và checksum chống ghi đè.
Snapshot/run cũ bất biến. Benchmark dùng snapshot riêng, không đổi theo web.

Trên trang Thời khóa biểu, bấm một buổi để đổi thứ, tiết hoặc phòng. Có hai
phạm vi: **Chỉ buổi này** đổi đúng occurrence của tuần đang xem (trong cùng
tuần), và **Toàn bộ các tuần hoạt động** đổi cùng pattern cho cả nhóm, kể cả
buổi đã có ngoại lệ. Hệ thống giữ nguyên giảng viên, plan và số tiết.
Chỉ cho chọn option từ snapshot gốc; Validator
kiểm tra toàn lịch trước khi lưu. Không gọi decoder để tự dời buổi khác và
không chạy lại thuật toán. Lịch nguồn cũ vi phạm hard capacity phải chạy lại
bài toán trước, không được âm thầm sửa hoặc coi là hợp lệ.

Mỗi lần lưu tạo `TimetableRevision` và đầy đủ `TimetableRevisionEntry`, có
parent, ghi chú và điểm fitness tính lại. `OptimizationRun`/`TimetableEntry`
gốc luôn giữ nguyên. Chọn bản gốc hoặc bản điều chỉnh bằng ô Phiên bản lịch;
JSON/CSV/XLSX cùng nhận `revision_id`. Đặt lại học kỳ xóa cả revision theo đúng
phạm vi, giữ nguyên dữ liệu nguồn như trước.

API điều chỉnh nhận `scope=ALL_WEEKS` (mặc định tương thích cũ) hoặc
`scope=SINGLE_SESSION` kèm `week_number`. Phương án riêng buổi lấy từ miền
nguyên tử của buổi và cùng giảng viên; phương án cả nhóm lấy giao toàn kỳ.
Menu chưa loại mọi xung đột với các buổi khác; kiểm tra toàn lịch ở lúc lưu.
Query chỉ cho phép tách mẫu theo tuần ở revision, bản gốc vẫn kiểm tra lặp
cố định. CSV/XLSX ghi đúng từng mẫu với tập tuần tương ứng, không nhân bản
ngoại lệ ra các tuần khác. Không cần thêm migration database.

Điểm revision mới dùng `preference_domain_mode=OCCURRENCE`: mong muốn tính
trong miền từng buổi, vì sửa tay không bị giới hạn bởi giao toàn kỳ. Metadata
lưu trong `fitness_breakdown_json`. Optimizer vẫn dùng mặc định `RECURRING`;
không dùng điểm revision chỉnh tay để so sánh benchmark.

Kiểm tra logic giao diện bằng Node (không cần cài thêm thư viện):

```bash
node --test "Core Algrithms/tests/web/schedule_adjustment.test.cjs" "Core Algrithms/tests/web/constraint_overview.test.cjs"
```

SQL smoke tự dựng đề bài nhỏ rồi rollback, bật `GAPO_SQL_SMOKE=1` và chạy
`python -m pytest "Core Algrithms/tests/test_occurrence_adjustment_sqlserver.py" -q`.

Endpoint bổ sung:

```text
GET  /api/input-data/form-schema
GET  /api/constraint-settings
PUT  /api/constraint-settings
GET  /api/runs/{run_id}/schedule-revisions
GET  /api/runs/{run_id}/adjustment-options
GET  /api/runs/{run_id}/schedule-quality
POST /api/runs/{run_id}/adjustment-preview
POST /api/runs/{run_id}/schedule-revisions
```

Trang Thời khóa biểu có mục **Chất lượng thời khóa biểu** chỉ đọc: hai điểm
tổng, điểm thành phần/trọng số/đóng góp và chi tiết phạt mong muốn theo giảng
viên. Phạm vi là toàn lịch, toàn học kỳ, không theo bộ lọc tuần/giảng viên.
Các điểm thành phần là điểm chuẩn hóa, không phải số lỗi hoặc phần trăm hài lòng.
Lịch gốc chấm theo RECURRING; bản điều chỉnh được chấm lại theo OCCURRENCE.

Điều chỉnh dùng luồng **Xem trước → Xác nhận và lưu phiên bản**. API preview
chỉ đọc, không tạo revision; trả các buổi đổi, lỗi hard kèm lớp/giảng viên/
phòng/ngày liên quan và điểm trước–sau. Cả hai lịch trong preview được chấm
theo OCCURRENCE để so cùng chuẩn, không so với điểm benchmark đã lưu.
Đổi phương án hoặc phạm vi phải xem trước lại. Lúc lưu vẫn kiểm tra toàn lịch;
không tin kết quả preview cũ và không tự dời buổi khác. Không đổi thuật toán,
Fitness, dữ liệu benchmark hay schema SQL.

## Benchmark thời khóa biểu

**Kịch bản đã lưu theo snapshot v2:** [benchmark_configs/target_po80_stress/README.md](benchmark_configs/target_po80_stress/README.md),
suite `benchmark_configs/target_po80_stress/timetable_stress_suite.json`; Small12/Medium18/
Large24 lớp,232/343/454buổi,D60/90/120. Snapshot đã khóa, không build lại từ DB.
N30/20vòng/trần630FE gồm30initial,seed1–10,Priority+Placement hard-only,
GA_PO mới là TARGET_PO80. Một lần chạy mới của ba phương pháp là90optimizer+3Greedy.

Code chính đã hỗ trợ snapshot v3 LT/TH độc lập, nhưng chưa chạy benchmark mô hình này.
Preflight trên dữ liệu tương ứng cho D72/108/144, số buổi không đổi. Không dùng
lại vector hoặc quần thể đầu v2 cho benchmark v3. Kiểm tra tích hợp và replay
tương thích bằng `tools/verify_part_assignment_integration.py`; các vector
chuyển đổi trong kiểm tra đó chỉ dùng xác minh, không phải kết quả thực nghiệm mới.

**Kết quả chính thức được chọn:** [benchmark_results/README.md](benchmark_results/README.md).
Gói `benchmark_results/island80_stress_d155/` giữ nguyên D155120optimizer+
3Greedy (có HYBRID50 đối chứng) và D1593run xác nhận bản ISLAND80 khi đó trùng chính xác.
Đọc báo cáo/ảnh trực tiếp; dữ liệu thô đầy đủ ở ZIP nén không mất dữ liệu, có
SHA từng file và lệnh kiểm tra độc lập. Không đổi nhãn ISLAND80 thành kết quả
GA_PO mới, không ghi đè evidence cũ hoặc trộn với bộ nhỏ trước đây.

FE thực tế được báo riêng vì decode/repair thất bại không tính FE. Greedy là
mốc xác định, không đưa vào kiểm định nhiều seed; không xếp hạng runtime các
worker song song. Kết quả cuối20vòng và commonFE đều được giữ, không chỉ lấy
tiêu chí thuận lợi. Các hướng dẫn `benchmark_configs/distributed/` và các
`distributed_results/` cũ là lịch sử, không phải bộ hiện hành.

Trước khi dùng schema đã tồn tại, chạy migration
`Script/migrate_2026_10_21_run_progress_control.sql` để thêm progress, timeout
và trạng thái `TIMED_OUT`, sau đó chạy
`Script/migrate_2026_10_22_durable_optimization_jobs.sql` để thêm cấu hình khôi
phục cùng thời điểm vào hàng đợi.

## Benchmark CEC 2022 lịch sử — cơ chế ISLAND80

Phần số học CEC lưu cơ chế ISLAND80 lịch sử, khác TARGET_PO80 hiện hành;
không dùng cơ chế trộn50/50 của runner lịch sử. Các toán tử/chọn lọc và
archive/migration được import từ core; chỉ thay cổng đánh giá bằng hàm CEC.
Vector cập nhật trên [0,1]^20 rồi chuyển x=-100+200u khi chấm. CEC không dùng
Encoder/Decoder; tính mới khi trao đổi nghiệm là khác vector chính xác.

Từ gốc repository:

```powershell
python "Core Algrithms/benchmark/launch_production_cec.py" --output "Core Algrithms/benchmark/results/cec2022_island80_moi" --workers 14
```

Lệnh đóng băng source và chạy mới1.080lượt:12hàm×30seed×3phương pháp,
N30/D20/300.000FE mỗi lượt gồm khởi tạo. Không đọc DB hoặc chạy lại benchmark
lịch. Các bước audit và tạo ảnh chỉ đọc kết quả đã lưu; xem
[benchmark/README.md](benchmark/README.md) và
[giao thức](benchmark/PRODUCTION_CEC_PROTOCOL.md).
