#!/usr/bin/env python
import json, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), "results")
WARMUP = 5          # in-process rows drop the first 5 of the 121 test contracts
TOL = 0.05          # the three CodeBERT runs must agree within 5 %

def ms(xs):
    return {"n": len(xs), "mean": 1000 * sum(xs) / len(xs), "median": 1000 * st.median(xs)}

def ms_from_stats(s):
    return {"n": s["n"], "mean": 1000 * s["mean"], "median": 1000 * s["median"]}

runs = [json.load(open(f"{RES}/codebert_run{k}.json"))["cuda:0"] for k in (1, 2, 3)]
order = runs[0]["contract_order"]
assert all(r["contract_order"] == order for r in runs)
run_means = [r["per_contract"]["mean"] for r in runs]
assert max(abs(x - st.median(run_means)) / st.median(run_means) for x in run_means) <= TOL
codebert = [st.median(r["per_contract_seconds_raw"][n] for r in runs) for n in order[WARMUP:]]

sdg = json.load(open(f"{RES}/sdg_times.json"))["rows"]
pipe = json.load(open(f"{RES}/pipeline_times.json"))
cpu = pipe["student_forward"]["cpu"]

rows = {
    "SDG construction": ms([r["seconds"] for r in sdg]),
    "SDG JSON read": ms_from_stats(pipe["sdg_json_read_seconds"]),
    "Node attribute encoding": ms_from_stats(pipe["encoding"]["cpu"]["per_contract"]),
    "CodeBERT statement embedding": ms(codebert),
    "Student forward, one member": ms_from_stats(cpu["one_member"]["per_contract"]),
    "Student forward, five members": ms_from_stats(cpu["ensemble_x5"]["per_contract"]),
    "Teacher propagation": ms_from_stats(pipe["teacher_seconds_cpu"]),
}
pipeline = ["SDG construction", "SDG JSON read", "Node attribute encoding",
            "CodeBERT statement embedding", "Student forward, five members"]
total = sum(rows[k]["mean"] for k in pipeline)
out = {
    "test_contracts": len(sdg),
    "rows_ms": rows,
    "five_member_pipeline_mean_ms": total,
    "share_of_pipeline_percent": {k: 100 * rows[k]["mean"] / total for k in pipeline},
    "not_in_pipeline_total": ["Student forward, one member", "Teacher propagation"],
}
json.dump(out, open(f"{RES}/INFERENCE_COST.json", "w"), indent=1)
for k, v in rows.items():
    print(f"{k:32s} {v['mean']:8.1f} {v['median']:8.1f}   (n={v['n']})")
print(f"Five-member pipeline mean: {total:.1f} ms/contract")
