import os
import sys
import json
import argparse

import torch
import torch.nn.functional as F

from torch.utils.data import DataLoader
from tqdm import tqdm


parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)


from utils.config import (
    DEVICE,
    GLOBAL_SEED,
    GlobalConfig,
    Stage2Config,
)

from utils.dataset import (
    PyGGraphDataset,
    split_dataset,
    collate_graphs_one_by_one,
)

from utils.model import RelationalGNN

from utils.ablation import apply_loss_flags, describe as describe_ablation

from utils.train_utils import (
    mask_edges,
    mask_node_features,
    set_seed,
    create_optimizer,
    create_scheduler,
    evaluate,
    EarlyStopping,
    save_checkpoint,
    load_checkpoint,
    train_epoch,
    binary_auc,
    tune_threshold,
    metrics_at_threshold,
)

from utils.losses import edge_reconstruction_loss, masked_node_loss


def load_labels(labels_file):
    labels_dict = {}

    with open(labels_file, "r") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            name, lbl = line.split(",")

            labels_dict[name] = int(lbl)

    return labels_dict


def build_stage2_config(
    stage1_config,
    global_cfg,
    stage2_cfg,
):
    config = {}

    inherited_keys = [
        "batch_size",
        "hidden_dim",
        "K",
        "lr",
        "weight_decay",
        "optimizer",
        "scheduler",
        "scheduler_factor",
        "scheduler_patience",
        "min_lr",
        "grad_clip",
    ]

    for key in inherited_keys:
        config[key] = stage1_config[key]

    config["stage_name"] = stage2_cfg.stage_name
    config["epochs"] = stage2_cfg.epochs
    config["target_accuracy"] = stage2_cfg.target_accuracy

    config["edge_dropout"] = stage2_cfg.edge_dropout

    config["node_mask_ratio"] = stage2_cfg.node_mask_ratio
    config["edge_mask_ratio"] = stage2_cfg.edge_mask_ratio

    config["use_teacher"] = False
    config["use_masking"] = True

    config["use_node_loss"] = True
    config["use_edge_loss"] = True

    config["use_trajectory"] = False
    config["use_sink_suppression"] = False

    config["node_loss_weight"] = stage2_cfg.node_loss_weight
    config["edge_loss_weight"] = stage2_cfg.edge_loss_weight

    config["early_stop_patience"] = global_cfg.early_stop_patience
    config["early_stop_min_delta"] = global_cfg.early_stop_min_delta

    apply_loss_flags(config)

    return config


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--encoded_folder",
        type=str,
        required=True,
    )

    parser.add_argument(
        "--labels_file",
        type=str,
        required=True,
    )

    parser.add_argument(
        "--stage1_checkpoint",
        type=str,
        default="checkpoints/stage1/stage1_best.pt",
    )

    parser.add_argument(
        "--stage1_config",
        type=str,
        default="checkpoints/stage0/best_stage0_config.json",
    )

    parser.add_argument(
        "--checkpoint_dir",
        type=str,
        default="checkpoints/stage2",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
    )

    parser.add_argument("--pairs_json", type=str, required=True)
    parser.add_argument("--pair_loss_weight", type=float, default=0.5)
    parser.add_argument("--pair_margin", type=float, default=0.2)
    parser.add_argument("--pair_n_sample", type=int, default=8)

    args = parser.parse_args()

    os.makedirs(
        args.checkpoint_dir,
        exist_ok=True,
    )

    set_seed(int(os.environ.get("RUN_SEED", GLOBAL_SEED)))

    global_cfg = GlobalConfig()
    stage2_cfg = Stage2Config()

    if not os.path.exists(args.stage1_config):
        raise FileNotFoundError(f"Missing config: {args.stage1_config}")

    with open(args.stage1_config, "r") as f:
        stage1_config = json.load(f)

    final_config = build_stage2_config(
        stage1_config=stage1_config,
        global_cfg=global_cfg,
        stage2_cfg=stage2_cfg,
    )

    print("\n===================================")
    print("STAGE 2 CONFIG")
    print("===================================\n")

    print(f"ABLATION: {describe_ablation()}")

    for k, v in final_config.items():
        print(f"{k}: {v}")

    labels_dict = load_labels(args.labels_file)

    dataset = PyGGraphDataset(
        encoded_folder=args.encoded_folder,
        labels_dict=labels_dict,
    )

    train_set, val_set, test_set = split_dataset(
        dataset=dataset,
        train_frac=global_cfg.train_split,
        val_frac=global_cfg.val_split,
        seed=int(os.environ.get("SPLIT_SEED",
                             os.environ.get("RUN_SEED", GLOBAL_SEED))),
        # SPLIT_SEED fixes the split; RUN_SEED sets the initialisation.
    )

    train_loader = DataLoader(
        train_set,
        batch_size=final_config["batch_size"],
        shuffle=True,
        collate_fn=collate_graphs_one_by_one,
        num_workers=global_cfg.num_workers,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=final_config["batch_size"],
        shuffle=False,
        collate_fn=collate_graphs_one_by_one,
        num_workers=global_cfg.num_workers,
    )

    test_loader = DataLoader(
        test_set,
        batch_size=final_config["batch_size"],
        shuffle=False,
        collate_fn=collate_graphs_one_by_one,
        num_workers=global_cfg.num_workers,
    )

    model = RelationalGNN(
        in_dim=dataset[0].x.shape[1],
        hidden_dim=final_config["hidden_dim"],
        edge_types=dataset.edge_type_mapping,
    ).to(DEVICE)

    optimizer = create_optimizer(
        model=model,
        lr=final_config["lr"],
        weight_decay=final_config["weight_decay"],
        optimizer_name=final_config["optimizer"],
    )

    scheduler = create_scheduler(
        optimizer=optimizer,
        scheduler_name=final_config["scheduler"],
        scheduler_params={
            "factor": final_config["scheduler_factor"],
            "patience": final_config["scheduler_patience"],
            "min_lr": final_config["min_lr"],
        },
    )

    if not os.path.exists(args.stage1_checkpoint):
        raise FileNotFoundError(f"Missing checkpoint: {args.stage1_checkpoint}")

    print("\n===================================")
    print("LOADING STAGE 1")
    print("===================================\n")

    checkpoint = torch.load(
        args.stage1_checkpoint,
        map_location=DEVICE,
    )

    model.load_state_dict(
        checkpoint["model"],
        strict=False,
    )

    print("Stage 1 weights loaded.")

    checkpoint_path = os.path.join(
        args.checkpoint_dir,
        "stage2_best.pt",
    )

    start_epoch = 0
    from utils.pair_loss import PairBank

    final_config["pair_loss_weight"] = args.pair_loss_weight
    final_config["pair_margin"] = args.pair_margin
    final_config["pair_n_sample"] = args.pair_n_sample

    pair_bank = PairBank(args.pairs_json, args.encoded_folder, DEVICE)
    print(f"[v6] pair ranking: {len(pair_bank)} train pairs, "
          f"weight={args.pair_loss_weight} margin={args.pair_margin} "
          f"n_sample={args.pair_n_sample}", flush=True)

    best_val_loss = float("inf")

    if args.resume and os.path.exists(checkpoint_path):
        start_epoch, best_val_loss = load_checkpoint(
            checkpoint_path,
            model,
            optimizer,
        )

        start_epoch += 1

        print(f"\nResumed stage2 from epoch " f"{start_epoch}")

    early_stopper = EarlyStopping(
        patience=final_config["early_stop_patience"],
        min_delta=final_config["early_stop_min_delta"],
        mode="min",
    )

    print("\n===================================")
    print("STAGE 2 TRAINING")
    print("===================================\n")

    for epoch in range(
        start_epoch,
        final_config["epochs"],
    ):
        print(f"\nEpoch " f"{epoch + 1}/{final_config['epochs']}")

        train_loss, train_stats = train_epoch(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            config=final_config,
            pair_bank=pair_bank,
        )

        val_loss, _, _, metrics, val_stats = evaluate(
            model=model,
            loader=val_loader,
            config=stage1_config,
        )

        if scheduler is not None:
            if isinstance(
                scheduler,
                torch.optim.lr_scheduler.ReduceLROnPlateau,
            ):
                scheduler.step(val_loss)

            else:
                scheduler.step()

        current_lr = optimizer.param_groups[0]["lr"]

        print(f"Train Loss : {train_loss:.4f}")
        print(f"Val Loss   : {val_loss:.4f}")
        print(f"Accuracy   : {metrics['accuracy']:.4f}")
        print(f"Precision  : {metrics['precision']:.4f}")
        print(f"Recall     : {metrics['recall']:.4f}")
        print(f"F1         : {metrics['f1']:.4f}")
        print(f"LR         : {current_lr:.6f}")

        print("\nStage2 Train Breakdown:")

        for k, v in train_stats.items():
            print(f"{k:20s}: {v:.6f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss

            save_checkpoint(
                checkpoint_path,
                model=model,
                optimizer=optimizer,
                epoch=epoch,
                val_loss=val_loss,
                config=final_config,
                metrics=metrics,
            )

            print("\nCheckpoint saved.")

        if metrics["accuracy"] >= final_config["target_accuracy"]:
            print("\nTarget accuracy reached.")
            break

        if early_stopper.step(val_loss):
            print("\nEarly stopping triggered.")
            break

    print("\n===================================")
    print("TEST EVALUATION")
    print("===================================\n")

    load_checkpoint(
        checkpoint_path,
        model,
        optimizer=None,
    )

    # clean-input evaluation (corrupt=False): reported test metrics must not
    # depend on random masking; masked eval is only for train/val loss parity

    test_loss, test_preds, test_labels, test_metrics, test_stats = evaluate(
        model=model,
        loader=test_loader,
        config=stage1_config,
        corrupt=False,
    )

    _, val_preds, val_labels, _, _ = evaluate(
        model=model,
        loader=val_loader,
        config=stage1_config,
        corrupt=False,
    )

    best_thr, val_f1 = tune_threshold(val_preds, val_labels)
    tuned = metrics_at_threshold(test_preds, test_labels, best_thr)

    print(f"Test Loss : {test_loss:.4f}")
    print(f"Accuracy  : {test_metrics['accuracy']:.4f}")
    print(f"Precision : {test_metrics['precision']:.4f}")
    print(f"Recall    : {test_metrics['recall']:.4f}")
    print(f"F1        : {test_metrics['f1']:.4f}")
    print(f"AUC       : {binary_auc(test_preds, test_labels):.4f}")
    print(f"F1@val-tuned thr {best_thr:.2f} (val F1 {val_f1:.4f}):")
    print(f"  F1 {tuned['f1']:.4f}  P {tuned['precision']:.4f}  "
          f"R {tuned['recall']:.4f}  Acc {tuned['accuracy']:.4f}")

    print("\nTest Loss Breakdown:")

    for k, v in test_stats.items():
        print(f"{k:20s}: {v:.6f}")


if __name__ == "__main__":
    main()

