from __future__ import annotations  # allow "int | None" annotations on Python 3.7 (mtl env)

from dataclasses import dataclass, asdict
import json
import os

import torch


@dataclass
class GlobalConfig:
    seed: int = 22
    device: str = "cuda:0"

    train_split: float = 0.70
    val_split: float = 0.15
    test_split: float = 0.15

    batch_size: int = 16
    num_workers: int = 0

    hidden_dim: int = 128
    K: int = 4

    optimizer: str = "adamw"
    weight_decay: float = 1e-4

    scheduler: str = "reduce_on_plateau"
    scheduler_factor: float = 0.5
    scheduler_patience: int = 3
    min_lr: float = 1e-6

    grad_clip: float = 5.0

    early_stop_patience: int = 10
    early_stop_min_delta: float = 1e-4

    checkpoint_dir: str = "checkpoints"

    deterministic: bool = False

DEVICE = torch.device(GlobalConfig.device if torch.cuda.is_available() else "cpu")
GLOBAL_SEED = GlobalConfig.seed

@dataclass
class OptuneConfig:
    optuna_trials: int = 25
    optuna_timeout: int | None = None

    target_accuracy: float = 0.75

    search_hidden_dims = [64, 96, 128, 192]
    search_K = [2, 3, 4, 5, 6]

    search_lr_min = 1e-4
    search_lr_max = 5e-3

    search_weight_decay_min = 1e-6
    search_weight_decay_max = 1e-3


@dataclass
class Stage0Config:
    stage_name: str = "stage0_sanity"

    lr: float = 5e-3

    edge_dropout: float = 0.0
    node_mask_ratio: float = 0.0
    edge_mask_ratio: float = 0.0

    epochs: int = 60

    use_teacher: bool = False
    use_node_loss: bool = False
    use_edge_loss: bool = False
    use_trajectory_loss: bool = False
    use_sink_suppression: bool = False

    graph_loss_weight: float = 1.0
    node_loss_weight: float = 0.0
    edge_loss_weight: float = 0.0
    trajectory_loss_weight: float = 0.0

    entropy_weight: float = 0.03
    sparsity_weight: float = 0.03
    smoothness_weight: float = 0.05
    sink_weight: float = 0.0

    target_accuracy: float = 0.75


@dataclass
class Stage1Config:
    stage_name: str = "stage1_teacher"

    lr: float = 1e-3

    edge_dropout: float = 0.10
    node_mask_ratio: float = 0.05
    edge_mask_ratio: float = 0.05

    epochs: int = 60

    use_teacher: bool = True
    use_node_loss: bool = True
    use_edge_loss: bool = True
    use_trajectory_loss: bool = True
    use_sink_suppression: bool = True

    graph_loss_weight: float = 1.0
    node_loss_weight: float = 0.8
    edge_loss_weight: float = 0.3
    trajectory_loss_weight: float = 0.2

    entropy_weight: float = 0.03
    sparsity_weight: float = 0.05
    smoothness_weight: float = 0.10
    sink_weight: float = 0.10

    target_accuracy: float = 0.85


@dataclass
class Stage2Config:
    stage_name: str = "stage2_masked"

    lr: float = 5e-4

    edge_dropout: float = 0.20
    node_mask_ratio: float = 0.20
    edge_mask_ratio: float = 0.20

    epochs: int = 100

    use_teacher: bool = True
    use_node_loss: bool = True
    use_edge_loss: bool = True
    use_trajectory_loss: bool = True
    use_sink_suppression: bool = True

    graph_loss_weight: float = 1.0
    node_loss_weight: float = 1.0
    edge_loss_weight: float = 0.5
    trajectory_loss_weight: float = 0.3

    entropy_weight: float = 0.02
    sparsity_weight: float = 0.05
    smoothness_weight: float = 0.15
    sink_weight: float = 0.10

    target_accuracy: float = 0.90


@dataclass
class Stage3Config:
    stage_name: str = "stage3_finetune"

    lr: float = 1e-4

    edge_dropout: float = 0.0
    node_mask_ratio: float = 0.0
    edge_mask_ratio: float = 0.0

    epochs: int = 40

    use_teacher: bool = False
    use_node_loss: bool = False
    use_edge_loss: bool = False
    use_trajectory_loss: bool = False
    use_sink_suppression: bool = False

    graph_loss_weight: float = 1.0
    node_loss_weight: float = 0.0
    edge_loss_weight: float = 0.0
    trajectory_loss_weight: float = 0.0

    entropy_weight: float = 0.0
    sparsity_weight: float = 0.0
    smoothness_weight: float = 0.03
    sink_weight: float = 0.0

    target_accuracy: float = 0.95


OPTUNA_SPACE = {
    "hidden_dim": [64, 128, 256],
    "K": [2, 3, 4, 5, 6],
    "lr": [1e-4, 5e-4, 1e-3, 5e-3],
    "weight_decay": [1e-6, 1e-5, 1e-4],
    "batch_size": [8, 16, 32],
    "edge_dropout": [0.0, 0.05, 0.1, 0.2],
}


def save_config(config, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w") as f:
        json.dump(asdict(config), f, indent=4)


def load_config(path):
    with open(path, "r") as f:
        return json.load(f)


def get_global_config():
    return GlobalConfig()


def get_stage0_config():
    return Stage0Config()


def get_stage1_config():
    return Stage1Config()


def get_stage2_config():
    return Stage2Config()


def get_stage3_config():
    return Stage3Config()


# Optional overrides of the Stage-1 teacher loss weights (TEACHER_LAMBDA_N/T).
# Not set for the final model.
def apply_teacher_weight_overrides(config, log=print):
    import os
    m = {"TEACHER_LAMBDA_N": "node_loss_weight",
         "TEACHER_LAMBDA_T": "trajectory_loss_weight"}
    hit = {}
    for env, key in m.items():
        v = os.environ.get(env)
        if v is not None:
            config[key] = float(v)
            hit[key] = float(v)
    if hit:
        log(f"[T2] teacher loss weights overridden: {hit}")
    return config

