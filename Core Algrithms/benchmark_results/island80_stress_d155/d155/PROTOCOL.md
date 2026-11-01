# D155 — Kiểm chứng chính thức ISLAND80 trên bộ stress D150

Người dùng yêu cầu chạy benchmark chính thức và tận dụng máy song song.
Đây là kiểm chứng ứng viên, CHƯA duyệt thay lai50/50 trong production.
Giữ nguyên source D153, DB/web, Fitness, hard/soft, nguồn dữ liệu và kết quả cũ.

## Thiết kế cố định trước chạy

- Byte-exact D150 Small/Medium/Large12/18/24lớp,232/343/454buổi,
  L+2B60/90/120. Không dùng bộ9/21/30gene cũ, không áp decoder mềm.
- N30,20vòng,trần630FE gồm30initial; retry5/node20000/repair3/init30000.
  Seed1–10 mỗi mức, theo cấu hình chính thức đã chốt. Seed này không trùng
  pilotD154111101/111102 hoặc pilotD150110101–110103 trên dữ liệu stress.
  Không gọi holdout mù vì đã khảo sát các fixture liên quan nhiều lần.
- GA/PO/HYBRID50/ISLAND80 ×3quymô×10seed =120run mới. Greedy deterministic
  chạy đúng1lần/bộ,3baseline riêng, không tham gia xếp hạng nhiều seed như optimizer.
- Mỗi case/seed có1initial30 bằng initialize_population chuẩn Random(seed),
  chia sẻ byteSHA cho cả4method. Không inject witness/chọn lại initial đẹp.
- Không reuse chất lượng hoặc prefix10vòng của pilot: công thức PO phụ thuộc
  tổng số vòng, nên10vòng không phải cùng quỹ đạo20vòng. Không ghép với kết
  quả GA/PO dữ liệu/representation khác để kết luận thắng.
- RAND đã dùng ở pilot, không chạy thêm30RAND nặng trong đợt này. Vì vậy
  benchmark chính này KHÔNG đủ để tự xác nhận lợi ích nhân quả của PO riêng.
  Greedy không đồng nghĩa random ablation.

## Cơ chế ứng viên giữ nguyên

source/islands.py byte-SHA bằng fileD154 đã thử. Chia24GA/6PO một lần bằng RNG
riêng theo seed, cảhai cậpnhậttoànchromosome. GA tournament/SBX/mutation và
elitist nội đảo; PO4hànhvi/helper/clipping/retry nguyên core, mean6PO/best riêng,
con hợp lệ thaycha dù xấu, hết retry giữcha. Global best riêng; archivePO6best
khác phenotype. Migration1migrantmỗihướng sau2/4/.../18vòng, không cuối20;
giữbest của đảo nhận, cho phép migrant tạm xấu hơn; không ép tournament dùng
migrant. Không khóa gene hoặc SECTION/POmutation. Không adaptive/tuning.

Ngân sách chung30offspringslots/vòng; không cấp630FE riêng cho mỗi đảo.
Migrant đã đánh giá không thêmFE, vector mới luôn qua Decoder/Repair/
Validator/Fitness chung. Failure không sinhfitnessgiả. Đếm FE thật,
attempts,repair/backtrack,PO worse accepted,4hànhvi,novelphenotype/migration/
GA parent PO-discovered vàbestgain thực.

## Đọc kết quả

So từđiển Q_general rồiQ_lecturer,tol1e-12; công bố thắng/hòa/thua từng mức,
tổng30cặp choISLAND80 soGA/PO/HYBRID50,cuối20gen vàexactcommonFE. Hòa
không tính thắng, không cộng2Q, không dùng trungvị riêng thay paired test.
Ghi sốlượt đứngnhất và tổngpairwin cho cả4method để tránh chọn cách đếm
thuận lợi sau khi biết điểm. Ghi exact sign test hai phía/bỏhòa vàHolm trên
3đối chứng ISLAND80, mô tảthăm dò vì nhiều nghiên cứu/tuning trước.
Không ép kết luận vượtGA hoặc mạnhnhất nếu kết quả không ủng hộ.

Lưu fullJSON/metrics/initial/checksum, denseFE, mọi kếtquả xấu;30initialcohort
và120checkpoint. Hậukiểmallbesthard0/fullfitness/entries,0softdecoderquery.
Trường hợp Greedy không tìm được lịch trong node/retry phải lưu thất bại,
không thay seed hoặc nới budget để làm baseline đẹp.

Ảnh từsavedJSON: hội tụmedian/IQR theo vòng vàFE,phân bố2Q,paired thắngthua/
gap,FE/failure/backtrack/scalability,Greedy mốc vàđónggópGA/PO;không rerun
optimizer chỉ để vẽ. Runtime workersong song không dùng xếp hạng tốc độ.

## Tài nguyên, an toàn và tái lập

Processworkers tối đa16/logicalCPU,RAMreserve1,5GiB vàadmission theoRSS
đo thực,BLAS1thread. Initialcohort tạo một lần; mỗi optimizerresult/detail/
checkpoint lưu ngay vàhậukiểm. Nếu dừng có thể resume các lượt chưa xong
sau kiểmsource/config/dataSHA; completedrun không chạy lại.

Mã nguồn chính, dữliệuD150,sourceD154giữ nguyên. Source/protocol/experiment
SHA frozen trước chạy. Không sửa frozen source để đổi kếtquả; nếu chỉ reporting
lỗi sau đủ120 thì sửa postcheck ngoài frozen source, không rerunoptimizer.
Không tự thêm phương pháp/tỷlệ hoặc thayseed/gia hạn đến khi thắng. Chỉ
chốt ứng dụng khi người dùng xem kếtquả vàduyệt riêng.

