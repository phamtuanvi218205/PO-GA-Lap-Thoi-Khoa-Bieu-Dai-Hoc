# GA–PO Timetabling — Python runtime

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

Theo D153 (01/11/2026), biểu diễn chính dùng chung cho GA, PO và GA–PO là
`RECURRING_PRIORITY_PLACEMENT.v1`, tích hợp từ bản D149 đã chạy pilot D150:

- Gene đầu chọn một giảng viên cho mỗi lớp học phần; LT và TH kế thừa cùng người.
- Mỗi khối buổi lặp có PriorityKey quyết định **thứ tự xếp**. Sắp tăng dần,
  bằng khóa thì theo ClassSession ID nhỏ nhất trong khối; không dùng MRV.
- Khóa PlacementKey riêng chọn hạng `min(floor(key*m), m-1)` trong **m mẫu
  hiện khả thi**, sau khi sắp thứ → tiết bắt đầu → phòng → index miền. Đây
  không phải chọn từ miền option tĩnh như biểu diễn cũ. Nếu bị kẹt, quay lui
  thử hạng gần nhất (k, k+1, k-1, ...), chỉ phục hồi hard feasibility trong
  ngân sách node. Không chấm mềm; Fitness đánh giá sau khi có lịch đầy đủ.
- Tổng số chiều là `L + 2B`: L gene giảng viên, B PriorityKey, B PlacementKey.
  Repair giữ chính sách đã thử: chỉ đổi giảng viên/priority, giữ placement.
- Mẫu được chọn vẫn cố định thứ–tiết–phòng trong mọi tuần hoạt động. Gene
  priority không bị viết lại thành chỉ số option; full Validator/Fitness cuối
  và các công thức GA/PO giữ nguyên. Cơ chế lai được chốt riêng ở D158 bên dưới.
- Mapping mới là `gene-option-mapping.v5`. Result JSON ghi `solver_pipeline`
  và `best_solution.vector_encoding` để replay đúng nghĩa vector.
- Kết quả lịch sử L+B vẫn đọc đúng nhãn DIRECT_OPTION, FEASIBILITY.v1 hoặc
  SOFT.v1, không tự thêm PlacementKey. Thiếu nhãn là DIRECT_OPTION. Chỉ dùng
  các nhánh này cho replay; không đổi nhãn hay ghi đè kết quả cũ.
- Không tiếp tục benchmark mới vào thư mục DIRECT cũ hoặc hợp nhất worker
  khác pipeline. Dùng thư mục kết quả mới; không xóa hay đổi nhãn kết quả cũ.
  Run chờ lưu từ pipeline cũ được báo không thể phục hồi và cần tạo run mới.

## Cơ chế lai đã chốt — D158 (01/11/2026)

`GA_PO` hiện chạy hai quần thể độc lập theo ứng viên ISLAND80 D154/D155:

- Mặc định GA 80% / PO 20% (N30 thành 24/6), mỗi quần thể ít nhất hai cá thể.
- Cả hai tối ưu toàn bộ chromosome; không khóa gene, không dùng PO làm mutation.
- GA giữ survivor selection cũ trong quần thể GA. PO dùng đủ bốn hành vi;
  con hợp lệ thay cha dù xấu hơn, có mean/best riêng và archive sáu lịch khác nhau.
- Trao đổi mỗi hai vòng, không trao đổi ở vòng cuối: mỗi hướng tối đa một lịch
  mới đối với bên nhận, bảo vệ best; hai nguồn được chụp trước migration.
- Hai bên dùng chung trần FE gồm khởi tạo. Không thay Fitness, Validator, GA/PO
  thuần, Decoder hay ngân sách. Không áp dụng survivor ưu tiên phenotype của PHENO80.
- Result/request-config ghi `hybrid_mechanism=GA_PO_ISLANDS.v1`. Job chờ 50/50
  cũ không tự phục hồi thành islands; kết quả cũ vẫn đọc được. Tỷ lệ tùy chỉnh
  khác 80/20 là cấu hình thử nghiệm khác, không được gắn với kết luận D155.
- Không dùng monkeypatch bộ chọn cha để đếm đóng góp trong code chạy API đồng thời.
  Unit test đối chiếu toàn bộ kết quả (trừ runtime) với reference D155 đã đóng băng.

Bộ nặng hiện hành nằm ở `benchmark_configs/stress/README.md`, snapshot byte-exact
D150, D60/90/120. Bộ `benchmark_configs/distributed/` cũ giữ làm lịch sử, không
ghi đè. D155 vẫn là bằng chứng đo trên bốn phương pháp cũ; không sửa kết quả sau
tích hợp. ISLAND80 thắng cặp cuối run GA16/14, PO17/13, không phải ưu thế thống kê
hoặc thắng ở mọi cách đo. Không tự chạy thêm benchmark khi tích hợp.

Luồng chạy chính:

1. đọc dữ liệu rời rạc từ SQL Server;
2. sinh `TeachingPlan` và mở rộng thành `ClassSession`;
3. tạo, kiểm tra và khóa `PlanningScenario`;
4. dựng snapshot `problem-instance.v2`;
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
POST /api/runs/{run_id}/schedule-revisions
```

## Benchmark thời khóa biểu

**Kịch bản hiện hành:** [benchmark_configs/stress/README.md](benchmark_configs/stress/README.md),
suite `benchmark_configs/stress/timetable_stress_suite.json`; Small12/Medium18/
Large24 lớp,232/343/454buổi,D60/90/120. Snapshot đã khóa, không build lại từ DB.
N30/20vòng/trần630FE gồm30initial,seed1–10,Priority+Placement hard-only,
GA_PO là ISLAND80. Một lần chạy mới của ba phương pháp là90optimizer+3Greedy.

**Kết quả chính thức được chọn:** [benchmark_results/README.md](benchmark_results/README.md).
Gói `benchmark_results/island80_stress_d155/` giữ nguyên D155120optimizer+
3Greedy (có HYBRID50 đối chứng) và D1593run xác nhận production trùng chính xác.
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
