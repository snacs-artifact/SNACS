#!/usr/bin/env python
import json, os, platform, statistics as st, sys, time
import torch
from transformers import AutoModel, AutoTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
VF = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
D = os.path.join(VF, "Dataset", "FINAL_CLEAN_DATASET")
SDG = os.path.join(VF, "Step_1_SDG", "sdg")
CB = os.path.join(VF, "Step_2_Preprocessing", "codebert_final")
MODEL, MAXLEN, BATCH, WARMUP = "microsoft/codebert-base", 64, 256, 5
DEV, DTYPE = "cuda:0", torch.float16
TEST = json.load(open(os.path.join(D, "split.json")))["test"]
assert len(TEST) == 121
assert torch.cuda.is_available(), "CodeBERT timing requires the GPU"

def stats(xs):
    xs = sorted(xs); n = len(xs)
    return {"n": n, "mean": sum(xs) / n, "sd": st.stdev(xs) if n > 1 else 0.0,
            "median": st.median(xs), "p95": xs[min(n - 1, int(round(0.95 * (n - 1))))],
            "min": xs[0], "max": xs[-1], "total": sum(xs)}

def sol_path(n):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{D}/{d}/{n}.sol"
        if os.path.exists(p):
            return p
    return None

def embed(g, n, tok, mdl):
    sp = sol_path(n)
    code = open(sp, "rb").read() if sp else b""
    texts = []
    for nd in g["nodes"]:
        m = nd.get("meta") or {}
        t = ""
        if code and "src_start" in m:
            raw = code[m["src_start"]:m["src_start"] + m["src_len"]]
            t = " ".join(raw.decode("utf8", "replace").split())
        if not t:
            t = " ".join((nd.get("label") or "").split())
        texts.append(t[:400])
    vecs = []
    with torch.no_grad():
        for i in range(0, len(texts), BATCH):
            b = tok(texts[i:i + BATCH], padding=True, truncation=True,
                    max_length=MAXLEN, return_tensors="pt").to(DEV)
            h = mdl(**b).last_hidden_state
            mask = b["attention_mask"].unsqueeze(-1).to(DTYPE)
            vecs.append(((h * mask).sum(1) / mask.sum(1).clamp(min=1)).cpu())
    return torch.cat(vecs).to(torch.float16)

torch.set_num_threads(1)
graphs = {n: json.load(open(os.path.join(SDG, n + ".json"))) for n in TEST}

t = time.perf_counter()
tok = AutoTokenizer.from_pretrained(MODEL)
mdl = AutoModel.from_pretrained(MODEL).to(DEV).eval().to(DTYPE)
torch.cuda.synchronize()
load_t = time.perf_counter() - t
torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()

times, raw, maxdiff, mincos = [], {}, 0.0, 1.0
for i, n in enumerate(TEST):
    t = time.perf_counter()
    e = embed(graphs[n], n, tok, mdl)
    torch.cuda.synchronize()
    dt = time.perf_counter() - t
    raw[n] = dt
    if i >= WARMUP:
        times.append(dt)
    ref = torch.load(os.path.join(CB, n + ".pt"))["emb"].float()
    e = e.float()
    maxdiff = max(maxdiff, float((e - ref).abs().max()))
    mincos = min(mincos, float(torch.nn.functional.cosine_similarity(e, ref, dim=1).min()))

out = {"host": platform.node(), "python": sys.version, "torch": torch.__version__,
       "n_test": len(TEST), "warmup_excluded": WARMUP, "batch": BATCH, "max_length": MAXLEN,
       "statements_per_contract": stats([len(graphs[n]["nodes"]) for n in TEST]),
       DEV: {"dtype": str(DTYPE), "gpu": torch.cuda.get_device_name(0),
             "per_contract": stats(times), "model_load_seconds": load_t,
             "frozen_parameters": sum(p.numel() for p in mdl.parameters()),
             "max_abs_diff_vs_shipped": maxdiff, "min_cosine_vs_shipped": mincos,
             "peak_gpu_mem_bytes": int(torch.cuda.max_memory_allocated()),
             "peak_gpu_reserved_bytes": int(torch.cuda.max_memory_reserved()),
             "contract_order": TEST, "per_contract_seconds_raw": raw}}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(f"{DEV} mean {out[DEV]['per_contract']['mean']*1000:.2f} ms  median {out[DEV]['per_contract']['median']*1000:.2f} ms  "
      f"max diff vs shipped {maxdiff}")
print("WROTE", sys.argv[1])
