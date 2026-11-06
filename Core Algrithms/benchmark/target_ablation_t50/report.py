"""Compare only saved T50 FULL references with completed ablation JSONs."""
from collections import Counter
from math import comb
from statistics import median
import evidence as w


def compare(a, b):
    for x, y in zip(a, b, strict=True):
        if abs(x-y) > 1e-12:
            return "W" if x < y else "L"
    return "T"


def sign(counts):
    n = counts["W"] + counts["L"]
    return min(1., 2*sum(comb(n,k) for k in range(min(counts["W"],counts["L"])+1))/2**n) if n else 1.


def report():
    w.verify_source()
    root = w.ROOT
    manifest = w.read(root / "manifest.json")
    methods = manifest["variants"]
    expected = {f"{s}_{seed}_{m}.json" for s in w.CASES for seed in range(1,11) for m in methods}
    for folder in ("runs", "details", "checkpoints"):
        if {p.name for p in (root / folder).glob("*.json")} != expected:
            raise ValueError(f"Missing or unexpected ablation files in {folder}; no main optimizer will be rerun.")
    rows, pairs, audits = [], [], []
    saved = {}
    reference = w.read(root / "reference_manifest.json")
    for relative, checksum in reference["entries_sha256"].items():
        assert w.digest((root / relative).read_bytes()) == checksum, relative
    for scale in w.CASES:
        prep = w.prepared(scale)
        for seed in range(1, 11):
            meta = w.read(root / "cohorts" / f"{scale}_{seed}.json")
            initial = min(record["quality"] for record in meta["records"])
            for method in ("FULL", *methods):
                name = f"{scale}_{seed}_{'TARGET_PO80' if method == 'FULL' else method}.json"
                base = root / "full" if method == "FULL" else root
                payload = w.read(base / "runs" / name)
                detail = w.read(base / "details" / name)
                cp = w.read(base / "checkpoints" / name)
                assert cp["result_sha"] == w.digest((base / "runs" / name).read_bytes())
                assert cp["detail_sha"] == w.digest((base / "details" / name).read_bytes())
                assert cp["initial_sha"] == detail["initial_sha"] == meta["initial_sha"]
                assert detail["records"][:30] == meta["records"]
                assert detail["trace"][:30] == meta["trace"]
                assert payload["snapshot_checksum"] == meta["snapshot_checksum"] == prep.snapshot_checksum
                assert detail["decoder_work"]["soft_option_scores"] == 0
                w.validate_trace(payload, detail)
                checked = w.audit(payload, prep)
                assert checked == detail["audit"]
                data = payload["result"]
                quality = [data["best_fitness"]["general_quality_score"], data["best_fitness"]["lecturer_preference_score"]]
                row = dict(scale=scale, seed=seed, method=method, quality=quality,
                    initial=initial, metrics=data["metrics"], history=data["convergence_history"],
                    activity_counts=data.get("hybrid_activity", {}).get("counts", {}))
                rows.append(row)
                saved[scale,seed,method] = dict(row=row, trace=detail["trace"])
                audits.append(dict(scale=scale, seed=seed, method=method, **checked))
    summary, tests = [], []
    for method in methods:
        for scale in w.CASES:
            for seed in range(1,11):
                full, other = saved[scale,seed,"FULL"], saved[scale,seed,method]
                fe = min(len(full["trace"]), len(other["trace"]))
                pairs.append(dict(scale=scale, seed=seed, control=method,
                    final=compare(full["row"]["quality"], other["row"]["quality"]),
                    common=compare(full["trace"][fe-1]["best"], other["trace"][fe-1]["best"]),
                    common_fe=fe, full_quality=full["row"]["quality"], control_quality=other["row"]["quality"],
                    common_full=full["trace"][fe-1]["best"], common_control=other["trace"][fe-1]["best"]))
        for scale in (*w.CASES,"ALL"):
            chosen = [p for p in pairs if p["control"] == method and (scale == "ALL" or p["scale"] == scale)]
            summary.append(dict(control=method, scale=scale,
                final=dict(Counter(p["final"] for p in chosen)), common=dict(Counter(p["common"] for p in chosen))))
    for endpoint in ("final", "common"):
        raw = {m: sign(Counter(p[endpoint] for p in pairs if p["control"] == m)) for m in methods}
        previous = 0.
        for index, method in enumerate(sorted(raw, key=raw.get)):
            previous = max(previous, min(1., raw[method]*(len(raw)-index)))
            tests.append(dict(endpoint=endpoint, control=method, p=raw[method], p_holm=previous,
                exploratory=True, family_size=len(methods), complete_three_control_family=(len(methods)==3)))
    aggregates = []
    for method in ("FULL", *methods):
        for scale in (*w.CASES, "ALL"):
            chosen = [r for r in rows if r["method"] == method and (scale == "ALL" or r["scale"] == scale)]
            counts = Counter()
            for r in chosen:
                counts.update(r["activity_counts"])
            aggregates.append(dict(method=method, scale=scale,
                qg_median=median(r["quality"][0] for r in chosen), ql_median=median(r["quality"][1] for r in chosen),
                FE=sum(r["metrics"]["fitness_evaluations"] for r in chosen),
                decode_fail=sum(r["metrics"]["decode_failed_count"] for r in chosen),
                backtracks=sum(r["metrics"]["total_decode_backtracks"] for r in chosen),
                qg_improved=sum(r["initial"][0]-r["quality"][0] > 1e-12 for r in chosen),
                activity_counts=dict(counts)))
    for name, data in (("rows",rows), ("pairs",pairs), ("summary",summary),
                        ("sign_tests",tests), ("quality_summary",aggregates)):
        w.save(root / "analysis" / f"{name}.json", data)
    plot(rows, pairs, methods)
    w.save(root / "analysis/final_audit.json", dict(passed=True, new_ablation_runs=30*len(methods),
        reused_full_results=30, rerun_main_algorithms=0, shared_initial_cohorts=30,
        hard_violations=0, soft_option_queries=0, iterations=50, fitness_cap=1530,
        independent_best_replays=audits))
    lines = ["# T50 ablation — LT/TH độc lập", "",
        f"Chỉ {30*len(methods)} lượt ablation mới; dùng30FULL T50 đã lưu. Không chạy lại GA/PO/FULL/Greedy.",
        "N30/T50/cap1530; cùng snapshotV3/30initial. W/T/L theo chiều FULL trước đối chứng.", "",
        "| Đối chứng | Bộ | Cuối50vòng W/T/L | CommonFE W/T/L |", "|---|---|---|---|"]
    for r in summary:
        count = lambda key: "/".join(str(r[key].get(k,0)) for k in "WTL")
        lines.append(f"|{r['control']}|{r['scale']}|{count('final')}|{count('common')}|")
    lines += ["", "Đọc quality_summary.json để xem haiQ trungvị riêng, FE/fail/backtrack và đónggóp.",
        "Kiểmđịnh sign-test2phía/Holm theo tập đối chứng có trong báo cáo chỉthămdò;",
        "nếu chạy riêng từng biến thể, cần merge đủ ba phần trước khi báo Holm3.",
        "Không xếp hạng runtime worker song song; giữ mọi seed/lượt bất lợi.",
        "NO_FEEDBACK chỉ tắt phản hồi ứng viên PO→GA; GA→PO và best chung còn hoạt động.",
        "RANDOM_GROUP giữ loại/kích thước nhóm dựa trên tiêu chí trội; chưa loại mọi thông tin mục tiêu."]
    (root / "KET_QUA.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def plot(rows, pairs, methods):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    output = w.ROOT / "analysis"
    for scale in w.CASES:
        fig, axes = plt.subplots(1,2,figsize=(12,4.5))
        for method in ("FULL", *methods):
            chosen = [r for r in rows if r["scale"] == scale and r["method"] == method]
            for ax, key in zip(axes, ("general_quality_score","lecturer_preference_score")):
                values = np.array([[h[key] for h in r["history"]] for r in chosen])
                lo, mid, hi = np.percentile(values,[25,50,75],axis=0)
                ax.plot(range(51),mid,label=method)
                ax.fill_between(range(51),lo,hi,alpha=.1)
                ax.set(xlabel="Generation", ylabel="Q_general" if key.startswith("general") else "Q_lecturer")
                ax.grid(alpha=.2); ax.legend()
        fig.suptitle(f"{scale.title()} — T50 ablation, 10 seeds")
        fig.tight_layout(); fig.savefig(output / f"{scale}_convergence.png",dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1,3,figsize=(13,4))
    for ax, scale in zip(axes,w.CASES):
        for method in methods:
            chosen = [p for p in pairs if p["scale"] == scale and p["control"] == method]
            ax.scatter([p["seed"] for p in chosen],
                [p["full_quality"][0]-p["control_quality"][0] for p in chosen],label=method)
        ax.axhline(0,color="black",linewidth=.8)
        ax.set(title=scale.title(),xlabel="Seed",ylabel="Qg FULL minus control")
        ax.legend(); ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(output / "paired_comparison.png",dpi=160); plt.close(fig)
