#!/usr/bin/env python
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
S3 = os.path.join(ROOT, "Step_4_Student")
T3 = os.path.join(ROOT, "Step_3_Teacher")
SDG_DIR = os.path.join(ROOT, "Step_1_SDG", "sdg")
ENC_DIR = os.path.join(ROOT, "Step_2_Preprocessing", "encoded_pyg")
sys.path.insert(0, S3)
for v in ("DROP_RELATIONS", "ABLATE_LOSS", "TAINT_ONLY_TEACHER"):
    os.environ.pop(v, None)
os.environ["SD_EDGE_WEIGHT"] = "0.7"

FAILURES = []

def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)

def relation_checks():
    import torch
    from utils.ablation import RELATION_NAMES, filter_pyg_edges, pinned_edge_type_mapping

    names = sorted(f[:-3] for f in os.listdir(ENC_DIR) if f.endswith(".pt"))[:40]
    graphs = [torch.load(os.path.join(ENC_DIR, n + ".pt"), weights_only=False, map_location="cpu") for n in names]
    for rel in RELATION_NAMES:
        rid = RELATION_NAMES.index(rel)
        removed, bad = 0, False
        for data in graphs:
            before = torch.bincount(data.edge_type, minlength=6)
            os.environ["DROP_RELATIONS"] = rel
            kept = filter_pyg_edges(data.clone())
            del os.environ["DROP_RELATIONS"]
            after = torch.bincount(kept.edge_type, minlength=6)
            removed += int(before[rid])
            bad |= int(after[rid]) != 0
            bad |= any(int(after[j]) != int(before[j]) for j in range(6) if j != rid)
            bad |= kept.edge_index.size(1) != int(after.sum())
        check(f"student: DROP_RELATIONS={rel} removes all {rel} edges and keeps the rest",
              removed > 0 and not bad, f"{removed} edges removed over {len(graphs)} graphs")
    check("vocabulary stays pinned at six relation codes",
          pinned_edge_type_mapping() == [str(i) for i in range(6)], str(pinned_edge_type_mapping()))

def noop_checks():
    import torch
    from utils.ablation import ablated_loss_terms, dropped_relations, filter_pyg_edges, filter_sdg_edges

    names = sorted(f[:-3] for f in os.listdir(ENC_DIR) if f.endswith(".pt"))[:10]
    same = True
    for n in names:
        d = torch.load(os.path.join(ENC_DIR, n + ".pt"), weights_only=False, map_location="cpu")
        o = filter_pyg_edges(d.clone())
        same &= torch.equal(o.edge_index, d.edge_index) and torch.equal(o.edge_type, d.edge_type)
        g = json.load(open(os.path.join(SDG_DIR, n + ".json")))
        same &= filter_sdg_edges(g)["edges"] == g["edges"]
    check("unset environment is a strict no-op", same and dropped_relations() == [] and ablated_loss_terms() == [])

def loss_flag_checks():
    import torch
    from utils.ablation import LOSS_TERMS, apply_loss_flags
    from utils.model import RelationalGNN
    from utils.train_utils import build_loss

    torch.manual_seed(0)
    n_nodes, in_dim, hidden = 12, 8, 16

    class Fake:
        pass

    data = Fake()
    data.x = torch.randn(n_nodes, in_dim)
    data.edge_index = torch.randint(0, n_nodes, (2, 30))
    data.edge_type = torch.randint(0, 6, (30,))
    data.y = torch.tensor([1.0])
    data.y_node = torch.rand(n_nodes, 2)
    data.y_graph_teacher = torch.tensor([0.7])
    data.y_node_trajectory = [
        {i: {"tainted": float(torch.rand(1)), "confidence": 1.0} for i in range(n_nodes)} for _ in range(3)]

    model = RelationalGNN(in_dim=in_dim, hidden_dim=hidden, edge_types=[str(i) for i in range(6)])
    model.eval()
    with torch.no_grad():
        h, hidden_states = model(data.x, data.edge_index, data.edge_type, K=2, return_hidden=True)

    base = {"graph_loss_weight": 1.0, "node_loss_weight": 0.8, "trajectory_loss_weight": 0.2,
            "entropy_weight": 0.03, "sparsity_weight": 0.05, "smoothness_weight": 0.10,
            "edge_consistency_weight": 0.05}
    full_cfg = apply_loss_flags(dict(base))
    with torch.no_grad():
        _, full = build_loss(model, data, h, full_cfg, hidden_states=hidden_states)

    owned = {"graph_teacher": "graph", "node": "node", "traj": "trajectory"}
    for term, key in owned.items():
        os.environ["ABLATE_LOSS"] = term
        cfg = apply_loss_flags(dict(base))
        del os.environ["ABLATE_LOSS"]
        with torch.no_grad():
            _, d = build_loss(model, data, h, cfg, hidden_states=hidden_states)
        removed = d["graph"] < full["graph"] - 1e-9 if term == "graph_teacher" else (key not in d and key in full)
        others = [k for k in ("entropy", "sparsity", "smoothness", "edge_consistency") if k in full]
        untouched = all(abs(d[k] - full[k]) < 1e-9 for k in others)
        check(f"loss: ABLATE_LOSS={term} removes {key} and nothing else", removed and untouched)

    os.environ["ABLATE_LOSS"] = "graph_teacher,node,traj"
    cfg = apply_loss_flags(dict(base))
    del os.environ["ABLATE_LOSS"]
    with torch.no_grad():
        _, d = build_loss(model, data, h, cfg, hidden_states=hidden_states)
    check("loss: ABLATE_LOSS=graph_teacher,node,traj removes all three teacher terms",
          "node" not in d and "trajectory" not in d and d["graph"] < full["graph"] - 1e-9)

    for term in ("node_rec", "link"):
        os.environ["ABLATE_LOSS"] = term
        cfg = apply_loss_flags(dict(base))
        del os.environ["ABLATE_LOSS"]
        k = LOSS_TERMS[term]
        check(f"loss: ABLATE_LOSS={term} sets {k}=False", cfg[k] is False and cfg["ablated_loss_terms"] == [term])

def taint_only_check():
    code = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from teacher_taint_engine import SDGTaintEngine, TAINT_ONLY
names = sorted(f[:-5] for f in os.listdir(sys.argv[2]) if f.endswith('.json'))[:40]
out = {n: SDGTaintEngine(json.load(open(os.path.join(sys.argv[2], n + '.json')))).run(max_iters=8)['y_graph'] for n in names}
print(json.dumps({'flag': TAINT_ONLY, 'y': out}))
"""
    res = {}
    for flag in ("0", "1"):
        env = dict(os.environ, TAINT_ONLY_TEACHER=flag, SD_EDGE_WEIGHT="0.7")
        r = subprocess.run([sys.executable, "-c", code, T3, SDG_DIR], env=env, capture_output=True, text=True, check=True)
        res[flag] = json.loads(r.stdout.strip().splitlines()[-1])
    changed = sum(res["0"]["y"][n] != res["1"]["y"][n] for n in res["0"]["y"])
    check("teacher: TAINT_ONLY_TEACHER=1 is read and changes the graph risk",
          res["1"]["flag"] is True and res["0"]["flag"] is False and changed > 0,
          f"y_graph changed on {changed}/{len(res['0']['y'])} graphs")

def main():
    print("Relation-drop switch (Table VII):")
    relation_checks()
    print("\nNo-op default:")
    noop_checks()
    print("\nLoss-term and teacher switches (Table VIII):")
    loss_flag_checks()
    taint_only_check()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("All ablation switches verified.")

if __name__ == "__main__":
    main()
