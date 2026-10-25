import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import MessagePassing


class RelationalGNN(MessagePassing):
    def __init__(self, in_dim, hidden_dim=128, edge_types=None, dropout=0.1,
                 recon_dim=None, text_dim=None, text_proj_dim=0):
        super().__init__(aggr="add")

        # The CodeBERT channel is enabled by the V7_CODEBERT_DIR env var.
        import os as _os

        if text_dim is None and _os.environ.get("V7_CODEBERT_DIR"):
            text_dim = int(_os.environ.get("V7_TEXT_DIM", 768))
            text_proj_dim = int(_os.environ.get("V7_TEXT_PROJ", 128))

        self.text_proj = None
        if text_dim and text_proj_dim:
            from utils.text_features import TextProjection
            self.text_proj = TextProjection(text_dim, text_proj_dim, dropout)
            # masking + node recovery stay on the ORIGINAL width; only the
            # encoder input widens by the projected text channel.
            in_dim = in_dim + text_proj_dim

        self.edge_types = edge_types or []
        self.hidden_dim = hidden_dim
        self.dropout = dropout

        self.node_encoder = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
        )

        self.edge_transforms = nn.ModuleDict(
            {
                str(etype): nn.Sequential(
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.ReLU(),
                    nn.LayerNorm(hidden_dim),
                    nn.Linear(hidden_dim, hidden_dim),
                )
                for etype in self.edge_types
            }
        )

        self.edge_gate = nn.ParameterDict({str(etype): nn.Parameter(torch.tensor(1.0)) for etype in self.edge_types})

        self.gru = nn.GRUCell(hidden_dim, hidden_dim)

        self.update_mlp = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(), nn.LayerNorm(hidden_dim), nn.Dropout(dropout)
        )

        self.node_risk_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden_dim // 2, 1)
        )

        self.graph_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden_dim, 1)
        )

        self.node_reconstruction_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, recon_dim if recon_dim else in_dim)
        )

        self.edge_classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.ReLU(), nn.Linear(hidden_dim, len(self.edge_types))
        )

        self.reset_parameters()

    def reset_parameters(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)

                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def apply_edge_dropout(self, edge_mask, edge_dropout, device):
        if (not self.training) or edge_dropout <= 0:
            return edge_mask

        keep = torch.rand(edge_mask.sum(), device=device) > edge_dropout

        idx = edge_mask.nonzero(as_tuple=False).view(-1)
        selected = idx[keep]

        if selected.numel() == 0:
            return edge_mask

        new_mask = torch.zeros_like(edge_mask, dtype=torch.bool)
        new_mask[selected] = True

        return new_mask

    def forward(self, x, edge_index, edge_type, K=4, edge_dropout=0.0, return_hidden=False):
        h = self.node_encoder(x)

        hidden_trajectory = [h] if return_hidden else None

        for _ in range(K):
            m = torch.zeros_like(h)

            for etype_idx, etype in enumerate(self.edge_types):
                mask = edge_type == etype_idx

                if mask.sum() == 0:
                    continue

                mask = self.apply_edge_dropout(mask, edge_dropout, h.device)

                src, dst = edge_index[:, mask]

                msg = self.edge_transforms[str(etype)](h[src])

                msg = msg * self.edge_gate[str(etype)]

                deg = torch.bincount(dst, minlength=h.size(0)).float().clamp(min=1)

                msg = msg / deg[dst].unsqueeze(-1)

                m[dst] += msg

            if (m == torch.nan).int().sum():
                print(m, h)

            # update_mlp is defined but not used: the update is GRU + LayerNorm.
            h = self.gru(m, h)

            h = F.layer_norm(h, h.shape[1:])

            if self.training:
                h = F.dropout(h, p=self.dropout)

            if return_hidden:
                hidden_trajectory.append(h)

        if return_hidden:
            return h, hidden_trajectory

        return h

    def get_node_logits(self, h):
        return self.node_risk_head(h).squeeze(-1)

    def get_node_risk(self, h):
        logits = self.get_node_logits(h)

        return torch.sigmoid(torch.clamp(logits, -15, 15))

    def graph_pool(self, h):
        mean_pool = h.mean(dim=0)

        max_pool = h.max(dim=0).values

        pooled = torch.cat([mean_pool, max_pool], dim=-1)

        return pooled

    def graph_score(self, h):
        pooled = self.graph_pool(h)

        logit = self.graph_head(pooled)

        return torch.sigmoid(torch.clamp(logit, -15, 15)).view(1)

    def reconstruct_nodes(self, h):
        return self.node_reconstruction_head(h)

    def predict_edge_type(self, h, edge_index):
        src, dst = edge_index

        edge_feat = torch.cat([h[src], h[dst]], dim=-1)

        logits = self.edge_classifier(edge_feat)

        return logits

    def freeze_representation(self):
        for param in self.node_encoder.parameters():
            param.requires_grad = False

        for param in self.edge_transforms.parameters():
            param.requires_grad = False

    def freeze_propagation(self):
        for param in self.gru.parameters():
            param.requires_grad = False

        for param in self.update_mlp.parameters():
            param.requires_grad = False

    def unfreeze_all(self):
        for param in self.parameters():
            param.requires_grad = True

