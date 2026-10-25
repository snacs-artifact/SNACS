#!/usr/bin/env python
import argparse
import hashlib
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DATA = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
ENC = os.path.join(ROOT, "Step_2_Preprocessing", "encoded_pyg")

ap = argparse.ArgumentParser()
ap.add_argument("--test-frac", type=float, required=True)
ap.add_argument("--val-frac", type=float, required=True,
                help="fraction of the WHOLE corpus held out for model selection, "
                     "taken from the non-test portion")
ap.add_argument("--seed", type=int, default=22, help="the seed the frozen split was drawn with")
ap.add_argument("--out", required=True)
a = ap.parse_args()
assert 0 < a.test_frac < 1 and 0 < a.val_frac < 1 and a.test_frac + a.val_frac < 1

labels = {}
for line in open(f"{DATA}/labels.csv"):
    p = line.strip().split(",")
    if len(p) >= 2 and p[1] in ("0", "1"):
        labels[p[0]] = int(p[1])
names = sorted(labels)
assert len(names) == 753, f"expected 753 contracts, found {len(names)}"

parent = {n: n for n in names}

def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x

def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[max(rx, ry)] = min(rx, ry)

def link_by(key_of, tag):
    buckets = {}
    for n in names:
        k = key_of(n)
        if k is None:
            continue
        buckets.setdefault(k, []).append(n)
    linked = 0
    for k, members in buckets.items():
        for m in members[1:]:
            union(members[0], m)
            linked += 1
    print(f"[groups] {tag}: {sum(1 for v in buckets.values() if len(v) > 1)} multi-member "
          f"keys, {linked} contracts merged")

_COMMENT = re.compile(rb"//[^\n]*|/\*.*?\*/", re.S)
_WS = re.compile(rb"\s+")

def sol_path(n):
    d = "vulnerable" if labels[n] == 1 else "non_vulnerable"
    return os.path.join(DATA, d, f"{n}.sol")

def norm_source(n):
    with open(sol_path(n), "rb") as f:
        src = f.read()
    return hashlib.md5(_WS.sub(b" ", _COMMENT.sub(b" ", src))).hexdigest()

def address_id(n):
    return n.lower() if re.fullmatch(r"0x[0-9a-fA-F]{40}", n) else None

def repr_sig(n):
    import torch
    g = torch.load(f"{ENC}/{n}.pt", map_location="cpu", weights_only=False)
    h = hashlib.md5()
    for t in (g.x, g.edge_index, g.edge_type):
        h.update(t.contiguous().numpy().tobytes())
    return h.hexdigest()

link_by(norm_source, "normalized source")
link_by(address_id, "contract identity (case-insensitive address)")
link_by(repr_sig, "encoded SDG representation")

groups = {}
for n in names:
    groups.setdefault(find(n), []).append(n)
multi = {k: v for k, v in groups.items() if len(v) > 1}
print(f"[groups] {len(groups)} groups over 753 contracts; {len(multi)} multi-member "
      f"({sum(len(v) for v in multi.values())} contracts)")

glabel = {}
for k, v in groups.items():
    s = sum(labels[n] for n in v)
    glabel[k] = 1 if s >= len(v) / 2 else 0

train_frac = 1.0 - a.test_frac - a.val_frac
rng = random.Random(a.seed)
out = {"train": [], "val": [], "test": []}
for cls in (1, 0):
    gs = sorted(k for k in groups if glabel[k] == cls)
    rng.shuffle(gs)
    n = len(gs)
    i = int(round(train_frac * n))
    j = int(round((train_frac + a.val_frac) * n))
    for part, chunk in (("train", gs[:i]), ("val", gs[i:j]), ("test", gs[j:])):
        for g in chunk:
            out[part].extend(sorted(groups[g]))
for part in out:
    out[part] = sorted(out[part])

assert sum(len(v) for v in out.values()) == 753
assert not (set(out["train"]) & set(out["val"])), "train/val overlap"
assert not (set(out["train"]) & set(out["test"])), "train/test overlap"
assert not (set(out["val"]) & set(out["test"])), "val/test overlap"
where = {n: p for p in out for n in out[p]}
for k, v in multi.items():
    assert len({where[n] for n in v}) == 1, f"group {k} spans partitions: {v}"

frozen = json.load(open(f"{DATA}/split.json"))
fw = {n: p for p in frozen for n in frozen[p]}
leak = sum(1 for n in out["test"] if fw.get(n) == "train")
print()
for p in ("train", "val", "test"):
    v = out[p]
    pos = sum(labels[n] for n in v)
    print(f"  {p:5s} {len(v):4d}  ({len(v)/753:5.1%})  vuln {pos:3d}  safe {len(v)-pos:3d}")
print(f"  train+val : test = {(len(out['train'])+len(out['val']))/753:.1%} : {len(out['test'])/753:.1%}")
print(f"  no group spans partitions; {len(multi)} multi-member groups kept intact")
print(f"  (for information only) {leak} of the {len(out['test'])} test contracts "
      f"are in the frozen split's TRAIN partition -- expected, this is a different draw")

os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
json.dump(out, open(a.out, "w"), indent=1)
meta = {"test_frac": a.test_frac, "val_frac": a.val_frac, "train_frac": round(train_frac, 4),
        "seed": a.seed, "counts": {p: len(out[p]) for p in out},
        "class_counts": {p: {"vuln": sum(labels[n] for n in out[p]),
                             "safe": len(out[p]) - sum(labels[n] for n in out[p])} for p in out},
        "grouping": ["normalized source", "case-insensitive address", "encoded SDG representation"],
        "n_groups": len(groups), "n_multi_member_groups": len(multi)}
json.dump(meta, open(os.path.splitext(a.out)[0] + "_meta.json", "w"), indent=1)
print(f"\nwritten -> {os.path.relpath(a.out, ROOT)}")
