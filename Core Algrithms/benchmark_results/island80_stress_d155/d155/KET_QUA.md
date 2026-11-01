# D155 — Benchmark chính thức ISLAND80 trên dữ liệu stress D150

Đủ120/120 optimizer run, 30 sharedinitialcohort; tất cả best hard0.
Giữ nguyên cơ chế D154, D153 encode/decode/Fitness; không áp dụng lai vào production.
N30/20vòng/trần630FE, seed1–10, bốn optimizer; Greedy1lần/bộ.

## So ISLAND80 — thắng/hòa/thua

| Đối chứng | Small cuối | Medium cuối | Large cuối | Tổng cuối | Tổng FE chung |
|---|---|---|---|---|---|
|GA|6/0/4|3/0/7|7/0/3|16/0/14|17/0/13|
|PO|4/0/6|6/0/4|7/0/3|17/0/13|13/0/17|
|HYBRID50|6/0/4|3/0/7|6/0/4|15/0/15|15/0/15|

## Hai Q trung vị riêng và chi phí

| Bộ | Method | Qg | QL | Best giảm/10 | FE thực | Decodefail | Backtrack |
|---|---|---:|---:|---:|---:|---:|---:|
|small|GA|0.034087|0.300776|10|6300|396|39435|
|small|PO|0.027939|0.317879|10|4826|10245|106779|
|small|HYBRID50|0.035002|0.324825|9|5562|5227|58443|
|small|ISLAND80|0.033153|0.319873|10|6004|2387|64498|
|medium|GA|0.044376|0.351941|10|6300|303|2180799|
|medium|PO|0.050770|0.340353|10|4566|11254|6390615|
|medium|HYBRID50|0.045757|0.329220|10|5450|5568|4679794|
|medium|ISLAND80|0.050974|0.348663|10|5966|2478|3184603|
|large|GA|0.058782|0.344289|10|6300|1944|64912633|
|large|PO|0.059973|0.322839|10|3494|17627|143385099|
|large|HYBRID50|0.063095|0.338491|10|5020|8890|81113962|
|large|ISLAND80|0.054631|0.338704|10|5747|4931|76796298|

## Kiểm định thăm dò

| Endpoint | So với | W/T/L | p raw | p Holm |
|---|---|---|---:|---:|
|final|GA|16/0/14|0.855536|1|
|final|PO|17/0/13|0.584665|1|
|final|HYBRID50|15/0/15|1|1|
|common|GA|17/0/13|0.584665|1|
|common|PO|13/0/17|0.584665|1|
|common|HYBRID50|15/0/15|1|1|

## Greedy (không kiểm định nhiều seed)

- small: COMPLETED, quality=[0.05468761083743842, 0.2982133468059227], reason=None.
- medium: COMPLETED, quality=[0.04661175368139224, 0.30479348913540005], reason=None.
- large: COMPLETED, quality=[0.06103392649903288, 0.30817024528157655], reason=None.

## Giới hạn

Không nhận đây là holdout mù: các fixture liên quan đã được nghiên cứu nhiều lần.
Không tính hòa thành thắng hoặc so hai trung vị riêng thay paired comparison.
Không chạy RAND ablation trong đợt này; pilot RAND còn3/3 cuối run, không quy gain riêng PO.
Runtime song song không dùng xếp hạng; FEcap không đồng nghĩa FE thực bằng nhau.
Tất cả số liệu và ảnh từ savedJSON; không rerun optimizer để vẽ hoặc thay seed khi thua.
Chưa chốt tích hợp lai mới; người dùng quyết định sau khi xem số liệu.

Chi tiết: analysis/rows.json,pairs.json,summary.json,sign_tests.json,ranks.json,baselines.json,final_audit.json.
Ảnh: ba convergence,quality_distribution,paired_comparison,paired_general_differences,search_cost_by_scale,
quality_by_scale,cooperation_contributions và ba thời khóa biểu từ seed trung vị.
