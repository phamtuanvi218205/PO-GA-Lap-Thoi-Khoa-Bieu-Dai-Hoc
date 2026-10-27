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
giảng dạy, phòng/lớp trực tuyến, thiết bị, lớp học phần, phần giảng dạy và lịch
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

## Benchmark thời khóa biểu

Cấu hình đã khóa nằm trong `benchmark_configs/`. Benchmark chính gồm một lần
`GREEDY_FIRST_FEASIBLE` làm mốc tham khảo và 10 seed cho từng phương pháp GA,
PO, GA–PO. Ba optimizer dùng population 30 và 20 vòng xử lý quần thể
(`max_fitness_evaluations=630` là giới hạn lý thuyết để suy ra số vòng); FE
thực tế được báo cáo riêng vì nghiệm lỗi bị loại trước Fitness. Greedy chỉ dựng
một lịch xác định nên không được đưa vào kiểm định nhiều seed. Xem
`benchmark_configs/README.md` để build snapshot, chạy pilot ba seed và sau đó
chạy bộ chính thức mà không đổi tham số.

Trước khi dùng schema đã tồn tại, chạy migration
`Script/migrate_2026_10_21_run_progress_control.sql` để thêm progress, timeout
và trạng thái `TIMED_OUT`, sau đó chạy
`Script/migrate_2026_10_22_durable_optimization_jobs.sql` để thêm cấu hình khôi
phục cùng thời điểm vào hàng đợi.
