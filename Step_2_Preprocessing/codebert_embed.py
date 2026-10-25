# codebert_embed.py
# Step 3: embeds the Solidity source statement of every SDG node with frozen
# microsoft/codebert-base (64 tokens, mean-pooled, fp16) and writes one
# {ids, emb} file per graph to codebert_final/. Nothing is fitted on the data;
# the 768->128 projection is learned inside the student.
import json, os, sys, glob
import torch

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDG = R + "/Step_1_SDG/sdg"
OUT = R + "/Step_2_Preprocessing/codebert_final"
MODEL = "microsoft/codebert-base"
MAXLEN = 64          # a statement, not a file
BATCH = 256


# Sources come only from the frozen FINAL_CLEAN_DATASET.
def sol_path(name):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{R}/Dataset/FINAL_CLEAN_DATASET/{d}/{name}.sol"
        if os.path.exists(p):
            return p
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    from transformers import AutoTokenizer, AutoModel
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(MODEL)
    mdl = AutoModel.from_pretrained(MODEL).to(dev).eval().half()
    print(f"CodeBERT loaded on {dev}", flush=True)

    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(f"{SDG}/*.json"))
    print(f"{len(names)} graphs", flush=True)
    done = miss_src = 0
    for gi, n in enumerate(names):
        dst = f"{OUT}/{n}.pt"
        if os.path.exists(dst):
            done += 1
            continue
        g = json.load(open(f"{SDG}/{n}.json"))
        sp = sol_path(n)
        code = open(sp, "rb").read() if sp else b""
        texts, ids = [], []
        for nd in g["nodes"]:
            m = nd.get("meta") or {}
            t = ""
            if code and "src_start" in m:
                raw = code[m["src_start"]:m["src_start"] + m["src_len"]]
                t = " ".join(raw.decode("utf8", "replace").split())
            if not t:                      # fall back to the IR label
                t = " ".join((nd.get("label") or "").split())
                miss_src += 1
            texts.append(t[:400]); ids.append(nd["id"])
        vecs = []
        with torch.no_grad():
            for i in range(0, len(texts), BATCH):
                b = tok(texts[i:i + BATCH], padding=True, truncation=True,
                        max_length=MAXLEN, return_tensors="pt").to(dev)
                h = mdl(**b).last_hidden_state          # [B,T,768]
                mask = b["attention_mask"].unsqueeze(-1).half()
                pooled = (h * mask).sum(1) / mask.sum(1).clamp(min=1)   # mean-pool
                vecs.append(pooled.cpu())
        emb = torch.cat(vecs).to(torch.float16) if vecs else torch.zeros(0, 768, dtype=torch.float16)
        torch.save({"ids": ids, "emb": emb}, dst)
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(names)}  (nodes without source text so far: {miss_src})", flush=True)
    print(f"DONE {done}/{len(names)}; nodes falling back to IR label: {miss_src}")


if __name__ == "__main__":
    main()
