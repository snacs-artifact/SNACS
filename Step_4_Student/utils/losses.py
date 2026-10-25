import torch
import torch.nn.functional as F


EPS = 1e-6

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def graph_loss(pred, y_true=None, y_teacher=None, class_weight=None, teacher_weight=0.30, focal_gamma=None):
    pred = pred.view(-1).clamp(EPS, 1 - EPS)

    total_loss = 0.0

    if y_true is not None:
        y_true = y_true.view(-1).float()

        pred = torch.nan_to_num(
            pred,
            nan=0.5,
            posinf=1.0,
            neginf=0.0,
        )

        bce = F.binary_cross_entropy(pred, y_true, reduction="none")

        if class_weight is not None:
            weight = torch.where(y_true > 0.5, class_weight, 1.0)

            bce = bce * weight

        if focal_gamma is not None:
            pt = torch.where(y_true > 0.5, pred, 1 - pred)

            focal = (1 - pt).pow(focal_gamma)

            bce = bce * focal

        total_loss += bce.mean()

    if y_teacher is not None:
        y_teacher = y_teacher.view(-1).float()

        y_teacher = y_teacher.clamp(EPS, 1 - EPS)

        teacher_loss = F.mse_loss(pred, y_teacher)

        total_loss += teacher_weight * teacher_loss

    return total_loss


def node_loss(pred_node, y_node, confidence=None, clean_weight=0.5, focal_gamma=None):
    if pred_node.dim() > 1:
        pred_node = pred_node.squeeze(-1)

    pred_node = pred_node.clamp(EPS, 1 - EPS)

    y_taint = y_node[:, 0].float()

    y_clean = y_node[:, 1].float()

    pred_node = torch.nan_to_num(
        pred_node,
        nan=0.5,
        posinf=1.0,
        neginf=0.0,
    )

    taint_loss = F.binary_cross_entropy(pred_node, y_taint, reduction="none")

    if focal_gamma is not None:
        pt = torch.where(y_taint > 0.5, pred_node, 1 - pred_node)

        focal = (1 - pt).pow(focal_gamma)

        taint_loss = taint_loss * focal

    if confidence is not None:
        confidence = confidence.float()

        taint_loss = taint_loss * confidence

    taint_loss = taint_loss.mean()

    clean_loss = F.mse_loss(1 - pred_node, y_clean)

    return taint_loss + clean_weight * clean_loss


def edge_loss(edge_pred, edge_target, edge_mask=None, confidence=None):
    edge_pred = edge_pred.clamp(EPS, 1 - EPS)

    edge_target = edge_target.float()

    loss = F.mse_loss(edge_pred, edge_target, reduction="none")

    if edge_mask is not None:
        loss = loss * edge_mask.float()

    if confidence is not None:
        loss = loss * confidence.float()

    return loss.mean()


def masked_node_loss(
    model,
    embeddings,
    original_x,
    node_mask,
):
    if node_mask.sum() == 0:
        return torch.tensor(
            0.0,
            device=embeddings.device,
        )

    # Target: the model's own encoding of the unmasked input (no gradient).

    with torch.no_grad():
        target_embeddings = model.node_encoder(original_x)

    return F.mse_loss(
        embeddings[node_mask],
        target_embeddings[node_mask],
    )


def edge_reconstruction_loss(
    embeddings,
    positive_edges,
):
    if positive_edges.size(1) == 0:
        return torch.tensor(
            0.0,
            device=embeddings.device,
        )

    src = positive_edges[0]
    dst = positive_edges[1]

    pos_scores = (embeddings[src] * embeddings[dst]).sum(dim=-1)

    pos_labels = torch.ones_like(pos_scores)

    pos_loss = F.binary_cross_entropy_with_logits(
        pos_scores,
        pos_labels,
    )

    num_nodes = embeddings.size(0)
    num_neg = positive_edges.size(1)

    neg_src = torch.randint(
        0,
        num_nodes,
        (num_neg,),
        device=embeddings.device,
    )

    neg_dst = torch.randint(
        0,
        num_nodes,
        (num_neg,),
        device=embeddings.device,
    )

    neg_scores = (embeddings[neg_src] * embeddings[neg_dst]).sum(dim=-1)

    neg_labels = torch.zeros_like(neg_scores)

    neg_loss = F.binary_cross_entropy_with_logits(
        neg_scores,
        neg_labels,
    )

    return 0.5 * (pos_loss + neg_loss)


def edge_type_loss(edge_logits, edge_target, edge_mask=None):
    if edge_mask is not None:
        edge_logits = edge_logits[edge_mask]

        edge_target = edge_target[edge_mask]

    if edge_logits.numel() == 0:
        return torch.tensor(0.0, device=edge_logits.device)

    return F.cross_entropy(edge_logits, edge_target.long())


# Auxiliary loss between intermediate node-risk scores and the teacher trajectory.
# Teacher targets are listed in sorted(node id) order.
def trajectory_loss(hidden_states, teacher_history, model, temporal_decay=0.90):
    steps = min(len(hidden_states), len(teacher_history))

    if steps == 0:
        return torch.tensor(0.0, device=DEVICE)

    total_loss = 0.0
    total_weight = 0.0

    for t in range(steps):
        h_t = hidden_states[t]

        teacher_t = teacher_history[t]

        y_taint = torch.tensor(
            [teacher_t[n]["tainted"] for n in sorted(teacher_t)], device=h_t.device, dtype=torch.float
        ).clamp(EPS, 1 - EPS)

        confidence = torch.tensor(
            [teacher_t[n].get("confidence", 1.0) for n in sorted(teacher_t)], device=h_t.device, dtype=torch.float
        )

        pred = model.get_node_risk(h_t).clamp(EPS, 1 - EPS)

        loss = ((pred - y_taint).pow(2) * confidence).mean()

        weight = temporal_decay**t

        total_loss += weight * loss

        total_weight += weight

    return total_loss / (total_weight + EPS)


def sink_suppression_loss(node_prob, edge_index, edge_type, edge_type_mapping):
    if "sd" not in edge_type_mapping:
        return torch.tensor(0.0, device=node_prob.device)

    sd_idx = edge_type_mapping.index("sd")

    _, dst = edge_index

    mask = edge_type == sd_idx

    if mask.sum() == 0:
        return torch.tensor(0.0, device=node_prob.device)

    dst_nodes = dst[mask]

    risky = node_prob[dst_nodes]

    return risky.mean()


def entropy_regularization(node_prob, strength=1.0):
    node_prob = node_prob.clamp(EPS, 1 - EPS)

    entropy = -(node_prob * torch.log(node_prob) + (1 - node_prob) * torch.log(1 - node_prob))

    return strength * entropy.mean()


def consistency_loss(pred_a, pred_b):
    pred_a = pred_a.clamp(EPS, 1 - EPS)

    pred_b = pred_b.clamp(EPS, 1 - EPS)

    return F.mse_loss(pred_a, pred_b)

