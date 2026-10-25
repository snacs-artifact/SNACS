import os
import re
import random
from collections import defaultdict

from torch.utils.data import Subset

_AUG = re.compile(r"_(vuln|safe)_aug\d+$")


def base_id(name):
    return _AUG.sub("", name)


def grouped_split_dataset(dataset, train_frac=0.7, val_frac=0.15, seed=22):
    # SPLIT_FILE: explicit split, JSON {train/val/test: [names]}. Graphs that are
    # not listed are excluded.
    split_file = os.environ.get("SPLIT_FILE")
    if split_file:
        import json
        with open(split_file) as f:
            lists = json.load(f)
        want = {s: set(lists[s]) for s in ("train", "val", "test")}
        idxs = {"train": [], "val": [], "test": []}
        for idx in range(len(dataset)):
            name = dataset[idx].graph_name
            for s in ("train", "val", "test"):
                if name in want[s]:
                    idxs[s].append(idx)
                    break
        print(f"[grouped_split] SPLIT_FILE={split_file}: "
              f"{len(idxs['train'])}/{len(idxs['val'])}/{len(idxs['test'])} "
              f"(excluded {len(dataset) - sum(map(len, idxs.values()))})")
        return (Subset(dataset, idxs["train"]), Subset(dataset, idxs["val"]),
                Subset(dataset, idxs["test"]))

    groups = defaultdict(list)
    for idx in range(len(dataset)):
        groups[base_id(dataset[idx].graph_name)].append(idx)

    group_label = {}
    for b, idxs in groups.items():
        orig = [int(dataset[i].y.item()) for i in idxs if dataset[i].graph_name == b]
        if orig:
            group_label[b] = orig[0]
        else:
            lbls = [int(dataset[i].y.item()) for i in idxs]
            group_label[b] = 1 if sum(lbls) >= len(lbls) / 2 else 0

    pos_groups = sorted([b for b in groups if group_label[b] == 1])
    neg_groups = sorted([b for b in groups if group_label[b] == 0])
    rng = random.Random(seed)
    rng.shuffle(pos_groups)
    rng.shuffle(neg_groups)

    def split_groups(gs):
        n = len(gs)
        a = int(train_frac * n)
        b = int((train_frac + val_frac) * n)
        return gs[:a], gs[a:b], gs[b:]

    p_tr, p_va, p_te = split_groups(pos_groups)
    n_tr, n_va, n_te = split_groups(neg_groups)

    def collect(gs):
        out = []
        for b in gs:
            out.extend(groups[b])
        return out

    train_idx = collect(p_tr) + collect(n_tr)
    val_idx = collect(p_va) + collect(n_va)
    test_idx = collect(p_te) + collect(n_te)
    rng.shuffle(train_idx)
    rng.shuffle(val_idx)
    rng.shuffle(test_idx)
    return (Subset(dataset, train_idx), Subset(dataset, val_idx), Subset(dataset, test_idx))

