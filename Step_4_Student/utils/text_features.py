import os
import torch
import torch.nn as nn

_CACHE = {}


# float32 [n_nodes, 768] aligned to the graph's node order; zeros if absent.
def load_text_emb(codebert_dir, name, n_nodes, device=None):
    key = (codebert_dir, name)
    if key not in _CACHE:
        p = os.path.join(codebert_dir, f"{name}.pt")
        if not os.path.exists(p):
            _CACHE[key] = None
        else:
            d = torch.load(p, map_location="cpu", weights_only=False)
            _CACHE[key] = d["emb"].float()
    e = _CACHE[key]
    if e is None or e.shape[0] != n_nodes:
        e = torch.zeros(n_nodes, 768)
    return e.to(device) if device is not None else e


class TextProjection(nn.Module):
    def __init__(self, in_dim=768, proj_dim=128, dropout=0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, proj_dim),
            nn.LayerNorm(proj_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

    def forward(self, e):
        return self.net(e)


def forward_with_text(model, d, K=3, edge_dropout=0.0, codebert_dir=None, name=None):
    import os
    x = d.x
    if getattr(model, "text_proj", None) is not None:
        cbd = codebert_dir or os.environ.get("V7_CODEBERT_DIR", "")
        nm = name if name is not None else getattr(d, "graph_name", "")
        e = load_text_emb(cbd, nm, x.shape[0], device=x.device)
        x = torch.cat([x, model.text_proj(e)], dim=1)
    return model(x, d.edge_index, d.edge_type, K=K, edge_dropout=edge_dropout)

