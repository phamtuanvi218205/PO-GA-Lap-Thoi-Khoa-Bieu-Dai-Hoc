# D159 — Xác nhận production ISLAND80 với benchmark D155

Người dùng duyệt test lại để kiểm chứng tích hợp, không yêu cầu benchmark
chất lượng mới hoặc thử biến thể. Chọn trước **seed1** (seed nhỏ nhất), cùng
seed cho Small/Medium/Large; không xem điểm để chọn seed đẹp.

Ba optimizer run mới, chỉ GA_PO production: N30/T20/cap630FE, retry5,
node20000/repair3/init30000, snapshot stress byte-exactD150, cấu hình0.8.
Tái khởi tạo từ Random(1), không load/reuse initial pickle cũ. Chạy song song
3process riêng; không SQL/web/production edits, không automation, không commit/push.

Gọi entry point production execute_prepared_run_request (cùng pipeline CLI/service).
Observer chỉ ghi nhận giá trị Fitness gốc trả về, không đổi điểm/RNG/vector/toán tử;
observer sống riêng trong từng worker. Kiểm sourceSHA/config/dataSHA đầu/cuối.

Đối chiếu D155 ISLAND80 cùng case/seed: 30 initial vectors/quality/phenotype/
components và initialSHA; toàn bộ từng Fitness Evaluation, dense best trace;
21mốc hội tụ; mọi metric trừ runtime; full best vector/options/fitness/entries/
mapping. Hai nhãn thuật toán ISLAND80 lịch sử và GA_PO production được phép khác,
request_id/hybrid_mechanism/thời gian không phải tiêu chí bằng nhau.

Gate tích hợp: tất cả đối chiếu trên phải **bằng chính xác**, hard0/fullcoverage,
decoder0softquery. Không dùng tolerance để biến lệch thành đạt. Nếu lệch hoặc
lỗi: lưu bằng chứng, báo lỗi cụ thể; không sửa cơ chế/seed/budget hoặc tự rerun.
Kết quả D155/các lần nghiên cứu khác chỉ đọc, không ghi đè/provenance relabel.

Đợt này chỉ kiểm equivalence integration trên ba trường hợp; không tính lại
thắng-thua30seed, không suy rộng thành ưu thế thống kê hoặc benchmark120run mới.
