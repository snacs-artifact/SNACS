#!/usr/bin/env python
import copy, io, json, os, platform, statistics as st, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
VF = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
S3 = os.path.join(VF, "Step_4_Student")
sys.path.insert(0, S3)
sys.path.insert(0, os.path.join(VF, "Step_3_Teacher"))
sys.path.insert(0, os.path.join(VF, "Step_2_Preprocessing"))
os.environ.setdefault("SD_EDGE_WEIGHT", "0.7")
CB = os.path.join(VF, "Step_2_Preprocessing", "codebert_final")
os.environ.setdefault("V7_CODEBERT_DIR", CB)

import torch
torch.set_num_threads(1)
from torch_geometric.data import Data  # noqa: F401  (unpickling encoded graphs)

D = os.path.join(VF, "Dataset", "FINAL_CLEAN_DATASET")
SDG = os.path.join(VF, "Step_1_SDG", "sdg")
ENC = os.path.join(VF, "Step_2_Preprocessing", "encoded_pyg")
PIPE = os.path.join(VF, "Step_2_Preprocessing", "encoder_transductive.pkl")
CKPT = os.path.join(VF, "checkpoints_final", "final_init%d", "stage2", "stage2_best.pt")
MEMBERS = [201, 202, 203, 204, 205]
WARMUP = 5
TEST = json.load(open(os.path.join(D, "split.json")))["test"]
assert len(TEST) == 121
REF = json.load(open(os.path.join(S3, "FINAL_RESULT.json")))["test"]["scores"]
DEVS = ["cpu", "cuda:0"] if torch.cuda.is_available() else ["cpu"]

def stats(xs):
    xs = sorted(xs); n = len(xs)
    return {"n": n, "mean": sum(xs) / n, "sd": st.stdev(xs) if n > 1 else 0.0,
            "median": st.median(xs), "p95": xs[min(n - 1, int(round(0.95 * (n - 1))))],
            "min": xs[0], "max": xs[-1], "total": sum(xs)}

def sync(dev):
    if dev.startswith("cuda"):
        torch.cuda.synchronize()

out = {"n_test": len(TEST), "warmup_excluded": WARMUP, "torch": torch.__version__,
       "python": sys.version, "host": platform.node(), "cpu_threads": torch.get_num_threads(),
       "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}

sdg, t_read = {}, []
for i, n in enumerate(TEST):
    t = time.perf_counter()
    with open(os.path.join(SDG, n + ".json")) as f:
        g = json.load(f)
    dt = time.perf_counter() - t
    sdg[n] = g
    if i >= WARMUP:
        t_read.append(dt)
out["sdg_json_read_seconds"] = stats(t_read)
out["graph_size"] = {"nodes": stats([len(sdg[n]["nodes"]) for n in TEST]),
                     "edges": stats([len(sdg[n]["edges"]) for n in TEST])}

import sdg_encoder as SE

shipped = {n: torch.load(os.path.join(ENC, n + ".pt"), map_location="cpu", weights_only=False)
           for n in TEST}
enc = {}
for dev in DEVS:
    SE.DEVICE = torch.device(dev)
    t = time.perf_counter()
    ck, fe, ae = SE.load_pipeline(PIPE)
    sync(dev)
    load_t = time.perf_counter() - t
    if dev.startswith("cuda"):
        torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    times, maxdiff, struct_ok = [], 0.0, True
    for i, n in enumerate(TEST):
        t = time.perf_counter()
        d = SE.encode_graph(sdg[n], n, ck, fe, ae)
        sync(dev)
        dt = time.perf_counter() - t
        if i >= WARMUP:
            times.append(dt)
        s = shipped[n]
        maxdiff = max(maxdiff, float((d.x - s.x).abs().max()))
        struct_ok &= torch.equal(d.edge_index, s.edge_index) and torch.equal(d.edge_type, s.edge_type)
    r = {"per_contract": stats(times), "pipeline_load_seconds": load_t,
         "max_abs_diff_vs_shipped_x": maxdiff, "edges_identical_to_shipped": bool(struct_ok)}
    if dev.startswith("cuda"):
        r["peak_gpu_mem_bytes"] = int(torch.cuda.max_memory_allocated())
        del ck, fe, ae; torch.cuda.empty_cache()
    enc[dev] = r
    print("encoding", dev, {k: v for k, v in r.items() if k != "per_contract"},
          round(r["per_contract"]["mean"] * 1000, 2), "ms", flush=True)
out["encoding"] = enc

from teacher_taint_engine import SDGTaintEngine

t_teach = []
for i, n in enumerate(TEST):
    g = copy.deepcopy(sdg[n])
    t = time.perf_counter()
    SDGTaintEngine(g).run(max_iters=8)
    dt = time.perf_counter() - t
    if i >= WARMUP:
        t_teach.append(dt)
out["teacher_seconds_cpu"] = stats(t_teach)
print("teacher", round(out["teacher_seconds_cpu"]["mean"] * 1000, 2), "ms", flush=True)

from utils.ablation import pinned_edge_type_mapping
from utils.model import RelationalGNN
from utils.text_features import load_text_emb

emb = {}
for n in TEST:
    e = load_text_emb(CB, n, shipped[n].x.shape[0])
    assert float(e.abs().sum()) > 0, n
    emb[n] = e
in_dim = shipped[TEST[0]].x.shape[1]

def build(dev):
    ms, lt = [], []
    for s in MEMBERS:
        t = time.perf_counter()
        c = torch.load(CKPT % s, map_location="cpu", weights_only=False)
        m = RelationalGNN(in_dim=in_dim, hidden_dim=c["config"].get("hidden_dim", 256),
                          edge_types=pinned_edge_type_mapping(), text_dim=768, text_proj_dim=128)
        m.load_state_dict(c["model"]); m.eval(); m.to(dev)
        sync(dev)
        lt.append(time.perf_counter() - t)
        ms.append((m, c["config"]["K"]))
    return ms, lt

def score(m, K, x, e, ei, et):
    return m.graph_score(m(torch.cat([x, m.text_proj(e)], dim=1), ei, et, K=K, edge_dropout=0.0))

fwd = {}
for dev in DEVS:
    models, load_ts = build(dev)
    assert {k for _, k in models} == {2}
    inp = [(shipped[n].x.to(dev), emb[n].to(dev), shipped[n].edge_index.to(dev),
            shipped[n].edge_type.to(dev)) for n in TEST]
    with torch.no_grad():
        for a in inp[:WARMUP]:
            for m, K in models:
                score(m, K, *a)
    sync(dev)
    res = {"checkpoint_load_seconds_per_member": stats(load_ts)}
    for tag, sel in (("one_member", models[:1]), ("ensemble_x5", models)):
        if dev.startswith("cuda"):
            torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        times, probs = [], []
        with torch.no_grad():
            for i, a in enumerate(inp):
                t = time.perf_counter()
                ps = [score(m, K, *a) for m, K in sel]
                sync(dev)
                dt = time.perf_counter() - t
                if i >= WARMUP:
                    times.append(dt)
                probs.append(sum(float(p) for p in ps) / len(ps))
        r = {"per_contract": stats(times)}
        if tag == "ensemble_x5":
            diff = max(abs(p - REF[n]) for p, n in zip(probs, TEST))
            r["max_abs_diff_vs_FINAL_RESULT"] = diff
            r["positives_at_0.5"] = sum(p > 0.5 for p in probs)
            r["positives_at_0.5_reference"] = sum(REF[n] > 0.5 for n in TEST)
        if dev.startswith("cuda"):
            r["peak_gpu_mem_bytes"] = int(torch.cuda.max_memory_allocated())
            r["peak_gpu_reserved_bytes"] = int(torch.cuda.max_memory_reserved())
        res[tag] = r
        print("forward", dev, tag, round(r["per_contract"]["mean"] * 1000, 2), "ms",
              {k: v for k, v in r.items() if k != "per_contract"}, flush=True)
    fwd[dev] = res
    del models, inp
    if dev.startswith("cuda"):
        torch.cuda.empty_cache()
out["student_forward"] = fwd

c0 = torch.load(CKPT % MEMBERS[0], map_location="cpu", weights_only=False)
mod = RelationalGNN(in_dim=in_dim, hidden_dim=256, edge_types=pinned_edge_type_mapping(),
                    text_dim=768, text_proj_dim=128)
mod.load_state_dict(c0["model"]); mod.eval()
INFER = ("text_proj", "node_encoder", "edge_transforms", "edge_gate", "gru", "graph_head")
per_mod = {name: sum(p.numel() for p in sub.parameters()) for name, sub in mod.named_children()}
per_mod["edge_gate"] = sum(p.numel() for p in mod.edge_gate.parameters())
total = sum(p.numel() for p in mod.parameters())
assert sum(per_mod.values()) == total, (per_mod, total)
n_buffers = sum(b.numel() for b in mod.buffers())

def nbytes(sd):
    b = io.BytesIO(); torch.save(sd, b); return b.getbuffer().nbytes

full_sd = mod.state_dict()
pruned = {k: v for k, v in full_sd.items() if k.split(".")[0] in INFER}
m2 = RelationalGNN(in_dim=in_dim, hidden_dim=256, edge_types=pinned_edge_type_mapping(),
                   text_dim=768, text_proj_dim=128)
miss = m2.load_state_dict(pruned, strict=False)
m2.eval()
eqdiff = 0.0
with torch.no_grad():
    for n in TEST:
        a = (shipped[n].x, emb[n], shipped[n].edge_index, shipped[n].edge_type)
        eqdiff = max(eqdiff, float((score(mod, 2, *a) - score(m2, 2, *a)).abs()))
out["parameters"] = {
    "config": {k: c0["config"].get(k) for k in ("K", "hidden_dim")},
    "in_dim": int(in_dim), "text_dim": 768, "text_proj_dim": 128,
    "checkpoint_keys": sorted(c0.keys()),
    "total_trainable": total, "buffers": n_buffers, "per_module": per_mod,
    "executed_at_inference": sum(per_mod[k] for k in INFER),
    "not_executed_at_inference": total - sum(per_mod[k] for k in INFER),
    "inference_modules": INFER,
    "ensemble_x5_total": 5 * total,
    "full_state_dict_bytes": nbytes(full_sd),
    "inference_only_state_dict_bytes": nbytes(pruned),
    "pruned_missing_keys": len(miss.missing_keys), "pruned_unexpected_keys": len(miss.unexpected_keys),
    "pruned_vs_full_max_abs_score_diff_test121": eqdiff,
    "checkpoint_file_bytes": os.path.getsize(CKPT % MEMBERS[0]),
    "checkpoint_file_bytes_x5": sum(os.path.getsize(CKPT % s) for s in MEMBERS),
    "codebert_frozen_params_note": "microsoft/codebert-base, counted in time_codebert.py",
}
print(json.dumps(out["parameters"], indent=1), flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1, default=str)
print("WROTE", sys.argv[1])
