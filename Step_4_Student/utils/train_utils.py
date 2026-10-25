import os
import math
import random
import numpy as np

import torch
import torch.nn.functional as F

from tqdm import tqdm
from torch.utils.data import DataLoader

from utils.losses import (
    edge_reconstruction_loss,
    graph_loss,
    masked_node_loss,
    node_loss,
    edge_loss,
    trajectory_loss,
    sink_suppression_loss,
    entropy_regularization,
    consistency_loss,
)

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def set_seed(seed=42):
    random.seed(seed)

    np.random.seed(seed)

    torch.manual_seed(seed)

    torch.cuda.manual_seed(seed)

    torch.cuda.manual_seed_all(seed)

    torch.backends.cudnn.deterministic = True

    torch.backends.cudnn.benchmark = False


def create_optimizer(model, lr=1e-3, weight_decay=1e-4, optimizer_name="adam"):
    optimizer_name = optimizer_name.lower()

    if optimizer_name == "adam":
        return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    if optimizer_name == "adamw":
        return torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    if optimizer_name == "sgd":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=weight_decay)

    raise ValueError(f"Unknown optimizer: {optimizer_name}")


def create_scheduler(optimizer, scheduler_name="plateau", scheduler_params=None):
    scheduler_params = scheduler_params or {}

    scheduler_name = scheduler_name.lower()

    if scheduler_name == "plateau":
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode="min",
            factor=scheduler_params.get("factor", 0.5),
            patience=scheduler_params.get("patience", 3),
            min_lr=scheduler_params.get("min_lr", 1e-6),
        )

    if scheduler_name == "step":
        return torch.optim.lr_scheduler.StepLR(
            optimizer,
            step_size=scheduler_params.get("step_size", 10),
            gamma=scheduler_params.get("gamma", 0.5),
        )

    if scheduler_name == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=scheduler_params.get("T_max", 50),
            eta_min=scheduler_params.get("eta_min", 1e-6),
        )

    return None


def save_checkpoint(checkpoint_path, model, optimizer, epoch, val_loss, metrics=None, config=None):
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)

    checkpoint = {
        "model": model.state_dict(),
        "epoch": epoch,
        "val_loss": val_loss,
    }

    if optimizer is not None:
        checkpoint["optimizer"] = optimizer.state_dict()

    if metrics is not None:
        checkpoint["metrics"] = metrics

    if config is not None:
        checkpoint["config"] = config

    torch.save(checkpoint, checkpoint_path)


def load_checkpoint(checkpoint_path, model, optimizer=None, map_location=DEVICE):
    checkpoint = torch.load(checkpoint_path, map_location=map_location)
    model.load_state_dict(checkpoint["model"])

    if optimizer is not None and "optimizer" in checkpoint:
        optimizer.load_state_dict(checkpoint["optimizer"])

    epoch = checkpoint.get("epoch", 0)
    val_loss = checkpoint.get("val_loss", float("inf"))

    return epoch, val_loss


def accuracy(scores, labels):
    preds = (scores > 0.5).float()

    return (preds == labels).float().mean().item()


def precision_recall_f1(scores, labels):
    preds = (scores > 0.5).float()

    tp = ((preds == 1) & (labels == 1)).sum().item()

    fp = ((preds == 1) & (labels == 0)).sum().item()

    fn = ((preds == 0) & (labels == 1)).sum().item()

    precision = tp / (tp + fp + 1e-6)

    recall = tp / (tp + fn + 1e-6)

    f1 = 2 * precision * recall / (precision + recall + 1e-6)

    return {"precision": precision, "recall": recall, "f1": f1}


def classification_metrics(scores, labels):
    metrics = precision_recall_f1(scores, labels)

    metrics["accuracy"] = accuracy(scores, labels)

    return metrics


def binary_auc(scores, labels):
    # threshold-free ranking quality (Mann-Whitney formulation)

    scores = scores.view(-1).tolist()
    labels = labels.view(-1).tolist()

    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]

    if not pos or not neg:
        return float("nan")

    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)

    return wins / (len(pos) * len(neg))


def metrics_at_threshold(scores, labels, threshold):
    scores = scores.view(-1)
    labels = labels.view(-1)

    preds = (scores > threshold).float()

    tp = ((preds == 1) & (labels == 1)).sum().item()
    fp = ((preds == 1) & (labels == 0)).sum().item()
    fn = ((preds == 0) & (labels == 1)).sum().item()

    precision = tp / (tp + fp + 1e-9)
    recall = tp / (tp + fn + 1e-9)
    f1 = 2 * precision * recall / (precision + recall + 1e-9)
    acc = (preds == labels).float().mean().item()

    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": acc}


def tune_threshold(scores, labels):
    # sweep 0.01..0.99; caller must pass VALIDATION scores only —
    # tuning on test would be leakage

    best_thr, best_f1 = 0.5, -1.0

    for i in range(1, 100):
        thr = i / 100.0

        f1 = metrics_at_threshold(scores, labels, thr)["f1"]

        if f1 > best_f1:
            best_f1, best_thr = f1, thr

    return best_thr, best_f1


class EarlyStopping:
    def __init__(self, patience=10, min_delta=1e-4, mode="min"):
        self.patience = patience

        self.min_delta = min_delta

        self.mode = mode

        self.best = None

        self.counter = 0

    def step(self, metric):
        if self.best is None:
            self.best = metric

            return False

        if self.mode == "min":
            improved = metric < (self.best - self.min_delta)

        else:
            improved = metric > (self.best + self.min_delta)

        if improved:
            self.best = metric

            self.counter = 0

        else:
            self.counter += 1

        return self.counter >= self.patience


def mask_node_features(x, mask_ratio=0.15):
    x = x.clone()

    num_nodes = x.size(0)
    num_mask = max(1, int(num_nodes * mask_ratio))
    perm = torch.randperm(num_nodes, device=x.device)
    mask_nodes = perm[:num_mask]

    original_x = x.clone()

    x[mask_nodes] = 0.0
    mask = torch.zeros(num_nodes, dtype=torch.bool, device=x.device)
    mask[mask_nodes] = True

    return x, original_x, mask


def mask_edges(data, mask_ratio):
    num_edges = data.edge_index.size(1)

    if num_edges == 0 or mask_ratio <= 0.0:
        empty = torch.empty(
            (2, 0),
            dtype=torch.long,
            device=data.edge_index.device,
        )

        empty_type = torch.empty(
            (0,),
            dtype=torch.long,
            device=data.edge_type.device,
        )

        return (
            data.edge_index,
            data.edge_type,
            empty,
            empty_type,
        )

    mask = (
        torch.rand(
            num_edges,
            device=data.edge_index.device,
        )
        < mask_ratio
    )

    keep_mask = ~mask

    kept_edges = data.edge_index[:, keep_mask]
    kept_types = data.edge_type[keep_mask]

    masked_edges = data.edge_index[:, mask]
    masked_types = data.edge_type[mask]

    return (
        kept_edges,
        kept_types,
        masked_edges,
        masked_types,
    )


def apply_graph_corruption(data, node_mask_ratio=0.0, edge_mask_ratio=0.0):
    data = data.clone()

    if node_mask_ratio > 0:
        (masked_x, original_x, node_mask) = mask_node_features(data.x, node_mask_ratio)

        data.x = masked_x

        data.original_x = original_x

        data.masked_node_mask = node_mask

    if edge_mask_ratio > 0:
        (edge_index, edge_type, edge_mask, _) = mask_edges(data, edge_mask_ratio)

        data.edge_index = edge_index

        data.edge_type = edge_type

        data.masked_edge_mask = edge_mask

    return data


def smoothness_loss(node_prob, edge_index):
    if edge_index.size(1) == 0:
        return torch.tensor(0.0, device=node_prob.device)

    src, dst = edge_index

    return ((node_prob[src] - node_prob[dst]) ** 2).mean()


def edge_consistency_loss(node_prob, edge_index):
    if edge_index.size(1) == 0:
        return torch.tensor(0.0, device=node_prob.device)

    src, dst = edge_index

    diff = torch.abs(node_prob[src] - node_prob[dst])

    return diff.mean()


def build_loss(model, data, h, config, hidden_states=None, masked_output=None):
    total_loss = 0.0
    loss_dict = {}

    graph_pred = model.graph_score(h)
    y_true = data.y.view_as(graph_pred).float()

    # Table IX: `w/o graph-level teacher loss` drops the lambda_g
    # MSE(y_hat, y_graph) term while keeping the ground-truth BCE.
    y_teacher = None
    if hasattr(data, "y_graph_teacher") and config.get("use_teacher_graph_loss", True):
        y_teacher = data.y_graph_teacher.view_as(graph_pred).float()

    g_loss = graph_loss(
        pred=graph_pred,
        y_true=y_true,
        y_teacher=y_teacher,
    )

    total_loss += config.get("graph_loss_weight", 1.0) * g_loss
    loss_dict["graph"] = g_loss.item()

    node_prob = model.get_node_risk(h)

    # Table IX: `w/o node alignment (L_node)`. Gated separately from
    # the stage-2 masked node RECOVERY term in train_epoch/evaluate, which
    # shares the `node_loss_weight` coefficient but is a different objective.
    if hasattr(data, "y_node") and config.get("use_teacher_node_loss", True):
        if data.y_node.numel() > 0:
            n_loss = node_loss(pred_node=node_prob, y_node=data.y_node)
            total_loss += config.get("node_loss_weight", 0.0) * n_loss
            loss_dict["node"] = n_loss.item()

    if hasattr(model, "predict_edges") and hasattr(data, "y_edge"):
        if data.y_edge.numel() > 0:
            edge_pred = model.predict_edges(h, data.edge_index)
            e_loss = edge_loss(edge_pred, data.y_edge)
            total_loss += config.get("edge_loss_weight", 0.0) * e_loss
            loss_dict["edge"] = e_loss.item()

    # Table IX: `w/o trajectory alignment (L_traj)`.
    if hidden_states is not None and hasattr(data, "y_node_trajectory") and config.get("use_traj_loss", True):
        traj_loss = trajectory_loss(hidden_states, data.y_node_trajectory, model)
        total_loss += config.get("trajectory_loss_weight", 0.0) * traj_loss
        loss_dict["trajectory"] = traj_loss.item()

    if masked_output is not None:
        if "recon_x" in masked_output and hasattr(data, "masked_node_mask"):
            recon_loss = masked_node_loss(model, masked_output["recon_x"], data.original_x, data.masked_node_mask)
            total_loss += config.get("reconstruction_loss_weight", 0.0) * recon_loss
            loss_dict["reconstruction"] = recon_loss.item()

    entropy = entropy_regularization(node_prob, strength=config.get("entropy_weight", 0.0))
    total_loss += entropy
    loss_dict["entropy"] = entropy.item()

    sparsity = node_prob.mean()
    total_loss += config.get("sparsity_weight", 0.0) * sparsity
    loss_dict["sparsity"] = sparsity.item()

    smooth = smoothness_loss(node_prob, data.edge_index)
    total_loss += config.get("smoothness_weight", 0.0) * smooth
    loss_dict["smoothness"] = smooth.item()

    edge_consistency = edge_consistency_loss(node_prob, data.edge_index)
    total_loss += config.get("edge_consistency_weight", 0.0) * edge_consistency
    loss_dict["edge_consistency"] = edge_consistency.item()

    if config.get("sink_suppression", False):
        suppress = sink_suppression_loss(node_prob, data.edge_index, data.edge_type, data.edge_type_mapping)
        total_loss += config.get("sink_weight", 0.0) * suppress
        loss_dict["sink"] = suppress.item()

    loss_dict["total"] = total_loss.item()
    return total_loss, loss_dict


def train_epoch(model, loader, optimizer, config, pair_bank=None):
    model.train()

    total_loss = 0.0

    aggregated = {
        "total": 0.0,
    }

    for batch in tqdm(loader, leave=False):
        optimizer.zero_grad()

        batch_loss = 0.0

        for data in batch:
            data = data.to(DEVICE)

            x_input = data.x
            edge_index_input = data.edge_index
            edge_type_input = data.edge_type

            masked_edges = None
            masked_types = None
            node_mask = None

            if config.get("edge_mask_ratio", 0.0) > 0:
                (
                    kept_edges,
                    kept_types,
                    masked_edges,
                    masked_types,
                ) = mask_edges(
                    data,
                    config["edge_mask_ratio"],
                )

                edge_index_input = kept_edges
                edge_type_input = kept_types

            if config.get("node_mask_ratio", 0.0) > 0:
                (
                    x_masked,
                    _,
                    node_mask,
                ) = mask_node_features(
                    data.x,
                    config["node_mask_ratio"],
                )

                x_input = x_masked

            # CodeBERT features are appended after masking, so masking and node
            # recovery act on the 32-d attributes only.
            x_full = data.x          # unmasked, in the SAME space the encoder sees
            if getattr(model, "text_proj", None) is not None:
                from utils.text_features import load_text_emb
                _e = load_text_emb(config.get("codebert_dir") or __import__("os").environ.get("V7_CODEBERT_DIR",""),
                                   getattr(data, "graph_name", ""),
                                   data.x.shape[0], device=x_input.device)
                _t = model.text_proj(_e)
                x_input = torch.cat([x_input, _t], dim=1)
                # masked_node_loss builds its target as node_encoder(original_x),
                # so original_x must live in the widened input space too.
                x_full = torch.cat([data.x, _t], dim=1)

            return_hidden = config.get("use_trajectory", False)

            output = model(
                x=x_input,
                edge_index=edge_index_input,
                edge_type=edge_type_input,
                K=config.get("K", 4),
                edge_dropout=config.get("edge_dropout", 0.0),
                return_hidden=return_hidden,
            )

            if return_hidden:
                h, hidden_states = output
            else:
                h = output
                hidden_states = None

            loss, loss_dict = build_loss(
                model=model,
                data=data,
                h=h,
                config=config,
                hidden_states=hidden_states,
            )

            # `use_link_loss` is the Table IX switch for L_link.
            if (
                config.get("use_edge_loss", False)
                and config.get("use_link_loss", True)
                and masked_edges is not None
                and masked_edges.numel() > 0
            ):
                edge_loss = edge_reconstruction_loss(
                    embeddings=h,
                    positive_edges=masked_edges,
                )

                loss = loss + config.get("edge_loss_weight", 1.0) * edge_loss

                loss_dict["edge_reconstruction"] = edge_loss.item()

            # `use_node_rec_loss` is the Table IX switch for L_node-rec.
            if (
                config.get("use_node_loss", False)
                and config.get("use_node_rec_loss", True)
                and node_mask is not None
                and node_mask.sum() > 0
            ):
                node_loss = masked_node_loss(
                    model=model,
                    embeddings=h,
                    original_x=x_full,
                    node_mask=node_mask,
                )

                loss = loss + config.get("node_loss_weight", 1.0) * node_loss

                loss_dict["masked_node"] = node_loss.item()

            batch_loss += loss

            for k, v in loss_dict.items():
                aggregated.setdefault(k, 0.0)

                if torch.is_tensor(v):
                    v = v.item()

                aggregated[k] += float(v)

        batch_loss = batch_loss / max(len(batch), 1)

        if pair_bank is not None and config.get("pair_loss_weight", 0.0) > 0:
            from utils.pair_loss import pair_ranking_loss

            pair_loss = pair_ranking_loss(
                model,
                pair_bank,
                K=config.get("K", 4),
                margin=config.get("pair_margin", 0.2),
                n_sample=config.get("pair_n_sample", 8),
            )

            batch_loss = batch_loss + config["pair_loss_weight"] * pair_loss

            aggregated.setdefault("pair_rank", 0.0)
            aggregated["pair_rank"] += float(pair_loss.item())

        batch_loss.backward()

        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            config.get("grad_clip", 5.0),
        )

        optimizer.step()

        total_loss += batch_loss.item()

    num_batches = max(len(loader), 1)

    aggregated["total"] = total_loss / num_batches

    for k in aggregated:
        aggregated[k] /= num_batches

    torch.cuda.empty_cache()

    return aggregated["total"], aggregated


def evaluate(model, loader, config, corrupt=True):
    # corrupt=True keeps val losses comparable to training (masking active).
    # corrupt=False evaluates on CLEAN inputs — required for reported test
    # metrics; masked-eval test numbers are randomly corrupted and noisy.

    model.eval()

    total_loss = 0.0

    preds = []
    labels = []

    aggregated = {
        "total": 0.0,
    }

    with torch.no_grad():
        for batch in loader:
            batch_loss = 0.0

            for data in batch:
                data = data.to(DEVICE)

                x_input = data.x
                edge_index_input = data.edge_index
                edge_type_input = data.edge_type

                masked_edges = None
                masked_types = None
                node_mask = None

                if corrupt and config.get("edge_mask_ratio", 0.0) > 0:
                    (
                        kept_edges,
                        kept_types,
                        masked_edges,
                        masked_types,
                    ) = mask_edges(
                        data,
                        config["edge_mask_ratio"],
                    )

                    edge_index_input = kept_edges
                    edge_type_input = kept_types

                if corrupt and config.get("node_mask_ratio", 0.0) > 0:
                    (
                        x_masked,
                        _,
                        node_mask,
                    ) = mask_node_features(
                        data.x,
                        config["node_mask_ratio"],
                    )

                    x_input = x_masked

                if corrupt and config.get("use_masking", False):
                    corrupted = apply_graph_corruption(
                        data,
                        node_mask_ratio=config.get("node_mask_ratio", 0.0),
                        edge_mask_ratio=config.get("edge_mask_ratio", 0.0),
                    )

                    x_input = corrupted.x
                    edge_index_input = corrupted.edge_index
                    edge_type_input = corrupted.edge_type

                # CodeBERT features must be appended last: the corruption branch
                # above replaces x_input.
                x_full = data.x          # unmasked, in the SAME space the encoder sees
                if getattr(model, "text_proj", None) is not None:
                    from utils.text_features import load_text_emb
                    _e = load_text_emb(config.get("codebert_dir") or __import__("os").environ.get("V7_CODEBERT_DIR", ""),
                                       getattr(data, "graph_name", ""),
                                       x_input.shape[0], device=x_input.device)
                    _t = model.text_proj(_e)
                    x_input = torch.cat([x_input, _t], dim=1)
                    x_full = torch.cat([data.x, _t], dim=1)

                return_hidden = config.get("use_trajectory", False)

                output = model(
                    x=x_input,
                    edge_index=edge_index_input,
                    edge_type=edge_type_input,
                    K=config.get("K", 4),
                    edge_dropout=0.0,  # disable stochastic dropout in eval
                    return_hidden=return_hidden,
                )

                if return_hidden:
                    h, hidden_states = output

                else:
                    h = output
                    hidden_states = None

                loss, loss_dict = build_loss(
                    model=model,
                    data=data,
                    h=h,
                    config=config,
                    hidden_states=hidden_states,
                )

                if (
                    config.get("use_edge_loss", False)
                    and config.get("use_link_loss", True)
                    and masked_edges is not None
                    and masked_edges.numel() > 0
                ):
                    edge_loss = edge_reconstruction_loss(
                        embeddings=h,
                        positive_edges=masked_edges,
                    )

                    loss = loss + config.get("edge_loss_weight", 1.0) * edge_loss

                    loss_dict["edge_reconstruction"] = edge_loss.item()

                if (
                    config.get("use_node_loss", False)
                    and config.get("use_node_rec_loss", True)
                    and node_mask is not None
                    and node_mask.sum() > 0
                ):
                    node_loss = masked_node_loss(
                        model=model,
                        embeddings=h,
                        original_x=x_full,
                        node_mask=node_mask,
                    )

                    loss = loss + config.get("node_loss_weight", 1.0) * node_loss

                    loss_dict["masked_node"] = node_loss.item()

                batch_loss += loss

                score = model.graph_score(h)

                preds.append(score.detach().cpu())

                labels.append(data.y.view_as(score).detach().cpu())

                for k, v in loss_dict.items():
                    aggregated.setdefault(k, 0.0)

                    if torch.is_tensor(v):
                        v = v.item()

                    aggregated[k] += float(v)

            batch_loss = batch_loss / max(len(batch), 1)

            total_loss += batch_loss.item()

    preds = torch.cat(preds)

    labels = torch.cat(labels)

    metrics = classification_metrics(
        preds,
        labels,
    )

    num_batches = max(len(loader), 1)

    aggregated["total"] = total_loss / num_batches

    for k in aggregated:
        aggregated[k] /= num_batches

    return (
        aggregated["total"],
        preds,
        labels,
        metrics,
        aggregated,
    )


def train_stage(model, train_loader, val_loader, optimizer, config, scheduler=None, checkpoint_path=None):
    best_val = float("inf")

    early_stop = EarlyStopping(patience=config.get("patience", 10), min_delta=config.get("min_delta", 1e-4), mode="min")

    history = []

    for epoch in range(config["epochs"]):
        train_loss, train_stats = train_epoch(model, train_loader, optimizer, config)

        (val_loss, preds, labels, metrics, val_stats) = evaluate(model, val_loader, config)

        if scheduler is not None:
            if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
                scheduler.step(val_loss)

            else:
                scheduler.step()

        current_lr = optimizer.param_groups[0]["lr"]

        print(f"Epoch {epoch+1}/{config['epochs']}")

        print(f"Train Loss: {train_loss:.4f}")

        print(f"Val Loss: {val_loss:.4f}")

        print(f"Accuracy: {metrics['accuracy']:.4f}")

        print(f"Precision: {metrics['precision']:.4f}")

        print(f"Recall: {metrics['recall']:.4f}")

        print(f"F1: {metrics['f1']:.4f}")

        print(f"LR: {current_lr:.6f}")

        history.append(
            {
                "epoch": epoch + 1,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "accuracy": metrics["accuracy"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
                "lr": current_lr,
            }
        )

        if val_loss < best_val:
            best_val = val_loss

            if checkpoint_path is not None:
                save_checkpoint(
                    checkpoint_path=checkpoint_path,
                    model=model,
                    optimizer=optimizer,
                    epoch=epoch,
                    val_loss=val_loss,
                    metrics=metrics,
                    config=config,
                )

                print(f"Checkpoint saved: " f"{checkpoint_path}")

        target_acc = config.get("target_accuracy", None)

        if target_acc is not None and metrics["accuracy"] >= target_acc:
            print("Target accuracy reached.")

            break

        if early_stop.step(val_loss):
            print("Early stopping triggered.")

            break

    return history


def loo_edge_type_eval(model, dataset, config, collate_fn):
    results = {}

    edge_types = dataset.edge_type_mapping

    for etype in edge_types:
        loader = DataLoader(dataset, batch_size=1, collate_fn=collate_fn)

        scores = []

        labels = []

        for batch in loader:
            for data in batch:
                data = data.to(DEVICE)

                etype_idx = data.edge_type_mapping.index(etype)

                mask = data.edge_type != etype_idx

                edge_index = data.edge_index[:, mask]

                edge_type = data.edge_type[mask]

                _x = data.x
                if getattr(model, "text_proj", None) is not None:
                    from utils.text_features import load_text_emb
                    _e = load_text_emb(config.get("codebert_dir") or __import__("os").environ.get("V7_CODEBERT_DIR", ""),
                                       getattr(data, "graph_name", ""),
                                       _x.shape[0], device=_x.device)
                    _x = torch.cat([_x, model.text_proj(_e)], dim=1)

                h = model(_x, edge_index, edge_type, K=config.get("K", 4))

                score = model.graph_score(h)

                scores.append(score.item())

                labels.append(data.y.item())

        scores = torch.tensor(scores)

        labels = torch.tensor(labels)

        results[etype] = {
            "accuracy": accuracy(scores, labels),
            "metrics": classification_metrics(scores, labels),
            "scores": scores,
            "labels": labels,
        }

    return results

