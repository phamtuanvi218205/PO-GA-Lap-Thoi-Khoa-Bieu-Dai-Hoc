# Benchmark GA, PO V2 va GA-PO

Thu muc nay danh gia ba thuat toan tren ham so hoc truoc khi dua vao bai toan
xep lich. Benchmark khong doc database va khong dung encoder/decoder lich.

## Nguyen tac cong bang

- Ba thuat toan dung cung ham, so chieu, mien tim kiem va kich thuoc quan the.
- Trong cung mot function va seed, ba thuat toan nhan ban sao cua cung mot
  quan the ban dau.
- Ngan sach duoc dem bang FE (fitness evaluations), khong chi bang iteration.
- Cung phep sua bien `clip` duoc dung sau khi sinh vi tri moi.
- Bao cao sai so `f_best - f*`, vi optimum cua CEC 2022 khong phai deu bang 0.
- Dung lai neu evaluator tra gia tri thap hon optimum qua sai so lam tron;
  khong ep sai so am ve 0 de che loi adapter.

## Ba profile

| Profile | Muc dich | Quy mo |
|---|---|---|
| `smoke` | Bat loi code va tao anh nhanh | 3 ham, D=10, 3 seed, 3.000 FE |
| `standard` | Ket qua so bo tren ham co ban | 9 ham, D=20, 10 seed, 30.000 FE |
| `cec2022_pilot` | Kiem tra ky thuat, khong tuning/bao cao | 12 ham, D=20, 3 seed, 30.000 FE |
| `cec2022` | Thuc nghiem chinh | 12 ham CEC 2022, D=20, 30 seed, 300.000 FE |

Profile `cec2022` rat lon: 12 x 3 x 30 = 1.080 lan chay, tong toi da
324 trieu FE. Can chay khi may co du thoi gian. Khong dung ket qua `smoke` lam
ket luan khoa hoc.

## Lenh chay

Mo terminal tai thu muc `Core Algrithms/benchmark`:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python run_benchmark.py --profile smoke
python run_benchmark.py --profile standard
python run_benchmark.py --profile cec2022_pilot
python run_benchmark.py --profile cec2022
```

Co the chia full CEC thanh cac shard seed doc lap, moi shard ghi mot output
rieng, sau do hop lai. Khong bao gio cho nhieu process ghi cung mot CSV:

```powershell
python run_benchmark.py --profile cec2022 --seed-start 1 --seed-end 8 --output results/cec2022_shard_01_08
python merge_cec2022_shards.py --inputs results/cec2022_shard_01_08 ... --output results/cec2022_official_full
```

Khi shard chay song song, chi so runtime bi anh huong boi tranh chap CPU. File
`merge_metadata.json` ghi ro dieu nay; ket qua fitness/FE van tai lap va doc lap.

Co the chi dinh noi luu ket qua:

```powershell
python run_benchmark.py --profile standard --output results/standard_chinh
```

`config.json` luu ca cau hinh thuc nghiem va dau vet giao thuc thuat toan.
Runner chi resume khi toan bo noi dung nay trung khop, nham tranh tron ket qua
cu va moi sau khi code, tham so hoac survivor selection thay doi.

Profile `cec2022_pilot` chi dung bat loi, uoc luong runtime va kiem tra output.
Khong dung ket qua pilot de tuning tham so hoac lam bang chung khoa hoc.

## File ket qua

- `raw_results.csv`: mot dong cho moi function - algorithm - seed.
- `summary.csv`: best, worst, mean, median, standard deviation va runtime.
- `convergence.csv`: best error theo tung moc FE.
- `ranks.csv`, `average_ranks.csv`: thu hang theo trung vi cua tung ham.
- `statistical_tests.csv`: Friedman va Wilcoxon co hieu chinh Holm.
- `01_convergence.png`: trung vi va khoang 25%-75% theo FE.
- `02_final_error_boxplots.png`: do on dinh cua sai so cuoi.
- `03_rank_heatmap.png`: thuat toan nao dung hang 1, 2, 3 tren tung ham.
- `04_runtime.png`: thoi gian voi cung ngan sach FE.

## Tham so dang dung

- GA: tournament size 3, SBX probability 0.9, SBX eta 15,
  polynomial mutation probability 1/D, mutation eta 20, elitism 1 ca the.
- PO: `beta=1.5`, dung bon cong thuc PO V2 da chot trong project.
- GA-PO: p=0.5; moi the he chia quan the thanh hai nhom, gop
  `P(t) + A' + B'`, giu N ca the tot nhat va xao tron.

Bo CEC 2022 chinh thuc giu nguyen cac tham so tren. Pilot khong duoc dung de
chon lai tham so tren chinh 12 ham se bao cao.

CEC 2022 duoc danh gia bang source C++ chinh thuc duoc pin commit va SHA-256.
Lan chay CEC dau tien se tai source vao `.cache/cec2022_official` va bien dich
DLL local; can Microsoft C++ Build Tools tren Windows. Nguon bo test:
https://github.com/P-N-Suganthan/2022-SO-BO
