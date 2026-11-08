"""Plot and summarize saved, independently audited GA/PO/ISLAND80 CEC runs.

This postprocessor imports no optimizer and performs no objective evaluation.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

METHODS=['GA','PO','ISLAND80']
COLORS=['#2364aa','#cf7a09','#087f65']

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def report(output: Path):
    out=output.resolve()
    assert json.loads((out/'status.json').read_text(encoding='utf8'))['status']=='COMPLETED'
    audit=json.loads((out/'independent_audit.json').read_text(encoding='utf8'))
    assert audit['runs_checked']==1080
    summary=read(out/'summary.csv');ranks=read(out/'average_ranks.csv')
    tests=read(out/'statistical_tests.csv');raw=read(out/'raw_results.csv')
    assert len(raw)==1080 and len(summary)==36
    traces=defaultdict(lambda:defaultdict(list))
    for x in read(out/'convergence.csv'):
        traces[(x['function'],x['algorithm'])][int(x['evaluations'])].append(float(x['best_error']))
    images=out/'analysis';images.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,
        'axes.labelsize':9,'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,'savefig.dpi':250})
    provenance=[]
    for group in range(4):
        fig,axes=plt.subplots(3,1,figsize=(6.,7.5),layout='constrained')
        for ax,number in zip(axes,range(group*3+1,group*3+4)):
            fn=f'CEC2022-F{number}'
            for method,color in zip(METHODS,COLORS):
                data=traces[(fn,method)];xs=sorted(data)
                assert len(xs)==501 and xs[0]==30 and xs[-1]==300000
                assert all(len(data[x])==30 for x in xs)
                q=np.maximum(np.array([np.quantile(data[x],[.25,.5,.75]) for x in xs]),1e-12)
                ax.plot(xs,q[:,1],label=method,color=color,lw=1.4)
                ax.fill_between(xs,q[:,0],q[:,2],color=color,alpha=.13)
            ax.set_title(fn);ax.set_yscale('log');ax.grid(alpha=.2)
            ax.set_xlabel('Số lần đánh giá hàm mục tiêu (FE)');ax.set_ylabel('Sai số tốt nhất (log)')
        axes[0].legend(ncol=3,loc='upper right')
        path=images/f'cec_convergence_{group+1}.png'
        fig.savefig(path,bbox_inches='tight',facecolor='white');plt.close(fig)
        provenance.append(dict(image=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source='convergence.csv',functions=list(range(group*3+1,group*3+4)),seeds=30,
            display_floor=1e-12))
    winners={m:[] for m in METHODS}
    lines=['# Kết quả CEC 2022 GA PO ISLAND80','',
        '12 hàm, D = 20, N = 30, seed 1–30; 300.000 FE gồm 30 FE khởi tạo. Đủ 1.080 lượt mới.',
        'Các cập nhật diễn ra trên u thuộc [0,1]; chấm tại x = -100 + 200u. ISLAND80 có',
        'hai quần thể 24/6, archive 6, migration mỗi 2 vòng trừ vòng cuối; nghiệm mới được phân biệt bằng vector chính xác.',
        'Mọi vector best/quần thể cuối, FE, quần thể đầu và SHA đã được hậu kiểm; xem independent_audit.json.',
        'Không dùng thời gian worker song song để xếp hạng tốc độ.','',
        '| Hàm | GA median error | PO median error | ISLAND80 median error |',
        '|---|---:|---:|---:|']
    for number in range(1,13):
        a={x['algorithm']:float(x['median_error']) for x in summary if x['function']==f'CEC2022-F{number}'}
        lines.append(f'| F{number} | '+' | '.join(f'{a[m]:.8g}' for m in METHODS)+' |')
        for m in METHODS:
            if a[m]==min(a.values()):winners[m].append(number)
    lines+=['','## Xếp hạng và kiểm định','',
        '| Phương pháp | Hạng trung bình trên 12 hàm | Hàm có trung vị thấp nhất (gồm đồng hạng) |',
        '|---|---:|---|']
    for m in METHODS:
        rank=next(x['average_rank'] for x in ranks if x['algorithm']==m)
        lines.append(f'| {m} | {float(rank):.6f} | '+', '.join(f'F{i}' for i in winners[m])+' |')
    lines+=['','| Kiểm định | So sánh | Thống kê | p | p Holm |','|---|---|---:|---:|---:|']
    for x in tests:
        lines.append('| '+' | '.join(str(x[k]) for k in ['test','comparison','statistic','p_value','holm_adjusted_p'])+' |')
    lines+=['','Các kiểm định dùng 12 trung vị theo hàm, không coi 1.080 lượt là 1.080 bài toán độc lập.',
        'Kết luận gắn với bộ hàm, tọa độ, D20 và ngân sách đã đo; không thay kết quả thời khóa biểu.',
        'Hình hội tụ dùng đủ 30 seed mỗi đường và đủ 12 hàm; vùng tô là Q1–Q3.',
        'Sai số bằng 0 chỉ được đặt ở 1e-12 khi hiển thị trục log; thống kê giữ nguyên.']
    (out/'KET_QUA.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    (out/'figure_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(runs=1080,winners=winners,average_ranks=ranks,plots=len(provenance)),ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    report(p.parse_args().output)
