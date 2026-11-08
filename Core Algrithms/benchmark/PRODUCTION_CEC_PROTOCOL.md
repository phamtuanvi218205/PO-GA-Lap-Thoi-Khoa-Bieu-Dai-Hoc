# CEC 2022 với cơ chế GA PO ISLAND80 của ứng dụng

Phiên bản giao thức cec2022-production-island80-v1. Khóa trước khi chạy.

- 12 hàm CEC 2022, D20, N30, seed 1–30, 300.000 FE gồm 30 khởi tạo.
- 1.080 lượt mới: GA, PO, ISLAND80. Không nhập điểm hoặc lịch sử từ bản lai 50/50.
- Evaluator C++ chính thức tại commit de20505283b76ec6bf17a2e8fc6052e655830691;
  checksum archive, DLL, input_data và source lưu trong config.json.
- Mỗi hàm/seed dùng cùng 30 vector khởi tạo và cùng SHA. Các stream thuật toán
  xác định bằng SeedSequence([seed, algorithm_index, 2026]); chỉ số GA1/PO2/ISLAND80 3.
- Các toán tử được import trực tiếp từ core hiện tại. GA dùng tournament3,
  SBX p0,9 eta15, polynomial mutation p1/D eta20; giữ N tốt nhất từ cha và con.
- PO dùng đủ bốn hành vi, mean đầu vòng, best riêng cập nhật ngay; con hữu hạn
  trong miền thay cha dù xấu hơn. Không có Decoder hoặc Repair trên bài toán số.
- ISLAND80 chia 24 GA/6 PO bằng Random(seed xor 0x1548020); archive PO tối đa6;
  di trú mỗi2 vòng, trừ vòng cuối; mỗi hướng tối đa1 vector mới so với đích,
  bảo vệ elite; cả hai hướng lấy nguồn trước di trú. GA không bị buộc chọn cha PO.
- Các phép cập nhật diễn ra trên u thuộc [0,1]^20 như code chính; chỉ gateway
  tính x=-100+200u rồi gọi CEC. Đây là quy ước tọa độ của phiên bản được đánh giá,
  không khẳng định tương đương quỹ đạo PO chạy trực tiếp trong [-100,100]^20.
- CEC không có phenotype lịch. Archive và migration dùng vector u khác nhau
  chính xác, không làm tròn, không đặt ngưỡng khoảng cách có thể tune.
- Nhánh lai được kiểm bằng so sánh toàn bộ vector, lịch sử và quần thể cuối
  với vòng lặp production trên gateway số; production/web/DB không sửa.
- Ngân sách cố định, không dừng sớm theo chất lượng. 9.999 vòng mới mỗi run,
  4.999 mốc di trú của ISLAND80. Di trú không gọi hàm mục tiêu lần nữa.
- Lưu JSON từng run, best vật lý và unit, trace FE/fitness và final population
  nén NPZ; chấm lại best độc lập ngoài ngân sách tối ưu và ghi rõ trong audit.
- Kết quả chính: sai số max(fbest-fopt,0), trung vị/IQR qua30 seed, hạng theo
  trung vị từng hàm; Friedman trên12 hàm, Wilcoxon ghép hàm và Holm3 cặp.
  Mọi so sánh và hình bao gồm toàn bộ12 hàm; không chọn hàm để tuyên bố ưu thế.
- Thời gian của worker song song chỉ mô tả vận hành, không xếp hạng tốc độ.
- Thư mục kết quả mới độc lập. Source đóng băng trong source/; không sửa khi
  đang chạy. Nếu lỗi thì lưu trạng thái, không tự giảm budget/đổi seed/tune.
  Chỉ resume khi được yêu cầu rõ ràng, không rerun kết quả đã lưu.
