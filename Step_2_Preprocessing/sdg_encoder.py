# sdg_encoder.py
# Step 2: turns each SDG into node feature tensors (encoded_pyg/).
# The encoder (categorical vocabulary, z-score, low-variance filter, autoencoder
# and PCA to 32-d) is fitted once on all 753 graphs without using any label,
# saved to encoder_transductive.pkl, and then applied unchanged to every graph.
import argparse
import hashlib
import json
import os
import sys
import time

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset, random_split
from torch_geometric.data import Data

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
UNK = 0                      # reserved index 0 in every categorical column
SEED = 22


def set_seed(s=SEED):
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


# ------------------------------------------------------------------ loading

def graph_name(fname):
    return fname[:-5] if fname.endswith(".json") else fname


# Loads the SDG JSONs; if `names` is given, only those graphs.
def load_graphs(folder, names=None):
    out, got = [], []
    want = set(names) if names is not None else None
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".json"):
            continue
        n = graph_name(f)
        if want is not None and n not in want:
            continue
        with open(os.path.join(folder, f)) as fh:
            out.append(json.load(fh))
        got.append(n)
    return out, got


# ------------------------------------------------------------------- vocab

# Column-wise vocabulary over the given graphs (all 753 in fit()). Index 0 is
# reserved for values not seen when the encoder was fitted.
def build_vocab(graphs):
    num_cols = len(graphs[0]["nodes"][0]["semantic"])
    vocab = []
    for col in range(num_cols):
        values = set()
        for g in graphs:
            for node in g["nodes"]:
                values.add(str(list(node["semantic"].values())[col]))
        # sorted() makes the mapping reproducible across runs
        vocab.append({v: i + 1 for i, v in enumerate(sorted(values))})
    return vocab


def cat_index(vocab, col, value):
    return vocab[col].get(str(value), UNK)


def extract_features(graphs, vocab, count_unk=False):
    binary, categorical = [], []
    n_unk = 0
    n_cat = 0
    for g in graphs:
        for node in g["nodes"]:
            binary.append([int(v) for v in node["features"].values()])
            row = []
            for i, v in enumerate(node["semantic"].values()):
                idx = cat_index(vocab, i, v)
                if count_unk:
                    n_unk += (idx == UNK)
                    n_cat += 1
                row.append(idx)
            categorical.append(row)
    b = torch.tensor(binary, dtype=torch.float32)
    c = torch.tensor(categorical, dtype=torch.long)
    return (b, c, n_unk, n_cat) if count_unk else (b, c)


# ------------------------------------------------------------------ modules

class FeatureEncoder(nn.Module):
    def __init__(self, vocab_sizes, emb_dim=8):
        super().__init__()
        self.embeddings = nn.ModuleList([nn.Embedding(v, emb_dim)
                                         for v in vocab_sizes])

    def forward(self, binary_x, categorical_x):
        embs = [emb(categorical_x[:, i]) for i, emb in enumerate(self.embeddings)]
        return torch.cat([binary_x] + embs, dim=1)


class Autoencoder(nn.Module):
    def __init__(self, input_dim, latent_dim=64):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_dim, 128), nn.ReLU(),
                                     nn.Linear(128, latent_dim))
        self.decoder = nn.Sequential(nn.Linear(latent_dim, 128), nn.ReLU(),
                                     nn.Linear(128, input_dim))

    def forward(self, x):
        return self.decoder(self.encoder(x))

    def encode(self, x):
        return self.encoder(x)


# Autoencoder over the node rows of all fitted graphs. Its internal 80/20 split
# of those rows is used only for its own early stopping.
def train_autoencoder(X, val_ratio=0.2, patience=5, max_epochs=1000, log=print):
    ds = TensorDataset(X)
    val_size = int(len(ds) * val_ratio)
    tr_size = len(ds) - val_size
    g = torch.Generator().manual_seed(SEED)
    tr, va = random_split(ds, [tr_size, val_size], generator=g)
    tl = DataLoader(tr, batch_size=256, shuffle=True)
    vl = DataLoader(va, batch_size=256, shuffle=False)

    model = Autoencoder(X.shape[1]).to(DEVICE)
    opt = optim.Adam(model.parameters(), lr=2e-3, weight_decay=1e-6)
    loss_fn = nn.MSELoss()
    sched = optim.lr_scheduler.ReduceLROnPlateau(opt, mode="min", factor=0.5,
                                                 patience=2)
    best, bad, best_state = float("inf"), 0, None
    for epoch in range(max_epochs):
        model.train()
        for (b,) in tl:
            b = b.to(DEVICE)
            opt.zero_grad()
            loss = loss_fn(model(b), b)
            loss.backward()
            opt.step()
        model.eval()
        vloss = 0.0
        with torch.no_grad():
            for (b,) in vl:
                b = b.to(DEVICE)
                vloss += loss_fn(model(b), b).item() * b.size(0)
        vloss /= max(val_size, 1)
        sched.step(vloss)
        if vloss < best:
            best, bad, best_state = vloss, 0, {k: v.clone() for k, v in
                                               model.state_dict().items()}
        else:
            bad += 1
        if epoch % 5 == 0:
            log(f"    AE epoch {epoch}: val={vloss:.6f} (best={best:.6f})")
        if bad >= patience:
            log(f"    AE early stop at epoch {epoch}, best val={best:.6f}")
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best


# --------------------------------------------------------------------- fit

def fit(sdg_folder, split_file, model_path, ae_max_epochs=1000, log=print):
    set_seed()
    split = json.load(open(split_file))
    train_names = set(split["train"]) | set(split["val"]) | set(split["test"])

    graphs, got = load_graphs(sdg_folder, train_names)
    got_set = set(got)

    # TRANSDUCTIVE: the fit population is every graph. No labels are used, so this
    # is unsupervised representation learning over the whole corpus.
    log(f"[fit] TRANSDUCTIVE: {len(got)} graphs "
        f"(train {len(set(split['train']) & got_set)}, "
        f"val {len(set(split['val']) & got_set)}, "
        f"test {len(set(split['test']) & got_set)})")
    log(f"[fit] NOTE: labels are NOT used in the fit; only feature statistics.")

    vocab = build_vocab(graphs)
    vocab_sizes = [len(v) + 1 for v in vocab]         # +1 for UNK at index 0
    log(f"[fit] vocab columns={len(vocab)} sizes={vocab_sizes}")

    binary, categorical = extract_features(graphs, vocab)
    n_rows = binary.shape[0]
    log(f"[fit] node rows: {n_rows}")
    binary, categorical = binary.to(DEVICE), categorical.to(DEVICE)

    encoder = FeatureEncoder(vocab_sizes).to(DEVICE)
    with torch.no_grad():
        X = encoder(binary, categorical)
        mean = X.mean(0, keepdim=True)
        std = X.std(0, keepdim=True) + 1e-6
        X = (X - mean) / std
        var = X.var(0)
        mask = var > 1e-4
        X = X[:, mask]
    log(f"[fit] after embed={tuple(X.shape)} kept {int(mask.sum())} of "
        f"{mask.numel()} columns")

    t0 = time.time()
    ae, ae_val = train_autoencoder(X, max_epochs=ae_max_epochs, log=log)
    log(f"[fit] AE trained in {time.time()-t0:.1f}s, best val MSE {ae_val:.6f}")

    with torch.no_grad():
        Z = ae.encode(X)
        pca_mean = Z.mean(0, keepdim=True)            # FITTED, not per-graph
        Zc = Z - pca_mean
        _, _, V = torch.pca_lowrank(Zc, q=32)
        pca_matrix = V[:, :32]
    log(f"[fit] PCA basis {tuple(pca_matrix.shape)}")

    payload = {
        "version": "v4",
        "vocab": vocab,
        "vocab_sizes": vocab_sizes,
        "unk_index": UNK,
        "encoder_state": encoder.state_dict(),
        "ae_state": ae.state_dict(),
        "pca_matrix": pca_matrix,
        "pca_mean": pca_mean,
        "mask": mask,
        "mean": mean,
        "std": std,
        "fit_provenance": {
            "split_file": os.path.abspath(split_file),
            "split_sha256": hashlib.sha256(
                open(split_file, "rb").read()).hexdigest(),
            "sdg_folder": os.path.abspath(sdg_folder),
            "n_fit_graphs": len(got),
            "n_fit_rows": int(n_rows),
            "fit_graph_names_sha256": hashlib.sha256(
                "\n".join(sorted(got)).encode()).hexdigest(),
            "n_heldout_excluded": 0,
            "heldout_in_fit": len(set(json.load(open(split_file))["val"]) | set(json.load(open(split_file))["test"])),
            "fit_regime": "TRANSDUCTIVE: unsupervised fit over train+val+test; no labels used",
            "seed": SEED,
            "ae_best_val_mse": float(ae_val),
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(model_path)), exist_ok=True)
    torch.save(payload, model_path)
    log(f"[fit] saved frozen pipeline -> {model_path}")
    return payload


# --------------------------------------------------------------- transform

def load_pipeline(model_path):
    ck = torch.load(model_path, map_location=DEVICE, weights_only=False)
    assert ck.get("version") == "v4", "not a v4 pipeline"
    enc = FeatureEncoder(ck["vocab_sizes"]).to(DEVICE)
    enc.load_state_dict(ck["encoder_state"])
    enc.eval()
    ae = Autoencoder(int(ck["mask"].sum().item())).to(DEVICE)
    ae.load_state_dict(ck["ae_state"])
    ae.eval()
    return ck, enc, ae


EDGE_TYPES = ["cf", "contains", "dd", "gd", "sd", "seq"]


# Encodes one graph with the frozen, already-fitted encoder; nothing is
# re-estimated from the incoming graph.
def encode_graph(graph, name, ck, enc, ae):
    binary, categorical = [], []
    n_unk = 0
    for node in graph["nodes"]:
        binary.append([int(v) for v in node["features"].values()])
        row = []
        for i, v in enumerate(node["semantic"].values()):
            idx = cat_index(ck["vocab"], i, v)
            n_unk += (idx == UNK)
            row.append(idx)
        categorical.append(row)
    b = torch.tensor(binary, dtype=torch.float32).to(DEVICE)
    c = torch.tensor(categorical, dtype=torch.long).to(DEVICE)

    with torch.no_grad():
        X = enc(b, c)
        X = (X - ck["mean"]) / ck["std"]        # frozen
        X = X[:, ck["mask"]]                    # frozen
        Z = ae.encode(X)                        # frozen
        Xf = torch.matmul(Z - ck["pca_mean"], ck["pca_matrix"])   # frozen mean

    ids = [n["id"] for n in graph["nodes"]]
    idx = {n: i for i, n in enumerate(ids)}
    et2i = {t: i for i, t in enumerate(EDGE_TYPES)}
    ei, et = [], []
    for e in graph["edges"]:
        ei.append([idx[e["from"]], idx[e["to"]]])
        et.append(et2i[e["type"]])
    if ei:
        edge_index = torch.tensor(ei, dtype=torch.long).t().contiguous()
        edge_type = torch.tensor(et, dtype=torch.long)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)
        edge_type = torch.empty((0,), dtype=torch.long)

    d = Data(x=Xf.cpu(), edge_index=edge_index)
    d.file_name = name
    d.edge_type = edge_type
    d.node_ids = ids
    d.edge_type_mapping = EDGE_TYPES
    d.n_unk_categorical = int(n_unk)
    return d


def transform_all(sdg_folder, model_path, out_dir, names=None, log=print):
    ck, enc, ae = load_pipeline(model_path)
    os.makedirs(out_dir, exist_ok=True)
    graphs, got = load_graphs(sdg_folder, names)
    stats = {"n": 0, "unk_rows": 0, "failed": {}}
    for g, n in zip(graphs, got):
        try:
            d = encode_graph(g, n, ck, enc, ae)
            torch.save(d, os.path.join(out_dir, f"{n}.pt"))
            stats["n"] += 1
            stats["unk_rows"] += d.n_unk_categorical
        except Exception as e:
            stats["failed"][n] = f"{type(e).__name__}: {str(e)[:150]}"
    log(f"[transform] encoded {stats['n']} graphs -> {out_dir} "
        f"({len(stats['failed'])} failed, {stats['unk_rows']} UNK categorical cells)")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdg_folder", required=True)
    ap.add_argument("--split_file", required=True)
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--out_dir", default="")
    ap.add_argument("--mode", choices=["fit", "transform", "both"], default="both")
    ap.add_argument("--ae_max_epochs", type=int, default=1000)
    a = ap.parse_args()

    if a.mode in ("fit", "both"):
        fit(a.sdg_folder, a.split_file, a.model_path,
            ae_max_epochs=a.ae_max_epochs)
    if a.mode in ("transform", "both"):
        assert a.out_dir, "--out_dir required for transform"
        transform_all(a.sdg_folder, a.model_path, a.out_dir)


if __name__ == "__main__":
    sys.exit(main())
