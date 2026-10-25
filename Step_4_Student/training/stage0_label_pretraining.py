import os
import sys
import json
import argparse

import torch
try:
    import optuna
except ImportError:
    optuna = None

from torch.utils.data import DataLoader

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from utils.config import (
    DEVICE,
    GLOBAL_SEED,
    GlobalConfig,
    Stage0Config,
    OptuneConfig,
    OPTUNA_SPACE,
)

from utils.dataset import (
    PyGGraphDataset,
    split_dataset,
    collate_graphs_one_by_one,
)

from utils.model import RelationalGNN

from utils.ablation import apply_loss_flags, describe as describe_ablation

from utils.train_utils import (
    set_seed,
    create_optimizer,
    create_scheduler,
    train_epoch,
    evaluate,
    EarlyStopping,
    save_checkpoint,
    load_checkpoint,
    binary_auc,
    tune_threshold,
    metrics_at_threshold,
)


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


def build_stage0_config(
    global_cfg,
    stage_cfg,
    tuned_params,
):
    config = {
        "stage_name": stage_cfg.stage_name,
        "epochs": stage_cfg.epochs,
        "target_accuracy": stage_cfg.target_accuracy,
        "hidden_dim": tuned_params["hidden_dim"],
        "K": tuned_params["K"],
        "optimizer": global_cfg.optimizer,
        "lr": tuned_params["lr"],
        "weight_decay": tuned_params["weight_decay"],
        "scheduler": global_cfg.scheduler,
        "scheduler_factor": tuned_params["scheduler_factor"],
        "scheduler_patience": tuned_params["scheduler_patience"],
        "min_lr": tuned_params["min_lr"],
        "batch_size": tuned_params["batch_size"],
        "edge_dropout": tuned_params["edge_dropout"],
        "use_masking": (tuned_params["node_mask_ratio"] > 0.0 or tuned_params["edge_mask_ratio"] > 0.0),
        "node_mask_ratio": tuned_params["node_mask_ratio"],
        "edge_mask_ratio": tuned_params["edge_mask_ratio"],
        "grad_clip": global_cfg.grad_clip,
        "entropy_weight": stage_cfg.entropy_weight,
        "sparsity_weight": stage_cfg.sparsity_weight,
        "smoothness_weight": stage_cfg.smoothness_weight,
        "sink_weight": stage_cfg.sink_weight,
        "use_teacher": False,
        "use_node_loss": False,
        "use_edge_loss": False,
        "use_trajectory": False,
        "use_sink_suppression": False,
        "graph_loss_weight": stage_cfg.graph_loss_weight,
        "node_loss_weight": stage_cfg.node_loss_weight,
        "edge_loss_weight": stage_cfg.edge_loss_weight,
        "trajectory_loss_weight": stage_cfg.trajectory_loss_weight,
        "early_stop_patience": global_cfg.early_stop_patience,
        "early_stop_min_delta": global_cfg.early_stop_min_delta,
    }

    apply_loss_flags(config)

    return config


def objective(
    trial,
    dataset,
    train_set,
    val_set,
):
    global_cfg = GlobalConfig()
    stage_cfg = Stage0Config()

    tuned_params = {
        "hidden_dim": trial.suggest_categorical(
            "hidden_dim",
            OPTUNA_SPACE["hidden_dim"],
        ),
        "K": trial.suggest_categorical(
            "K",
            OPTUNA_SPACE["K"],
        ),
        "lr": trial.suggest_categorical(
            "lr",
            OPTUNA_SPACE["lr"],
        ),
        "weight_decay": trial.suggest_categorical(
            "weight_decay",
            OPTUNA_SPACE["weight_decay"],
        ),
        "batch_size": trial.suggest_categorical(
            "batch_size",
            OPTUNA_SPACE["batch_size"],
        ),
        "edge_dropout": trial.suggest_categorical(
            "edge_dropout",
            OPTUNA_SPACE["edge_dropout"],
        ),
        "scheduler_factor": trial.suggest_float(
            "scheduler_factor",
            0.1,
            0.8,
        ),
        "scheduler_patience": trial.suggest_int(
            "scheduler_patience",
            2,
            8,
        ),
        "min_lr": trial.suggest_float(
            "min_lr",
            1e-7,
            1e-4,
            log=True,
        ),
        "node_mask_ratio": trial.suggest_float(
            "node_mask_ratio",
            0.0,
            0.25,
        ),
        "edge_mask_ratio": trial.suggest_float(
            "edge_mask_ratio",
            0.0,
            0.25,
        ),
    }

    config = build_stage0_config(
        global_cfg=global_cfg,
        stage_cfg=stage_cfg,
        tuned_params=tuned_params,
    )

    train_loader = DataLoader(
        train_set,
        batch_size=config["batch_size"],
        shuffle=True,
        collate_fn=collate_graphs_one_by_one,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=config["batch_size"],
        shuffle=False,
        collate_fn=collate_graphs_one_by_one,
    )

    model = RelationalGNN(
        in_dim=dataset[0].x.shape[1],
        hidden_dim=config["hidden_dim"],
        edge_types=dataset.edge_type_mapping,
    ).to(DEVICE)

    optimizer = create_optimizer(
        model=model,
        lr=config["lr"],
        weight_decay=config["weight_decay"],
        optimizer_name=config["optimizer"],
    )

    scheduler = create_scheduler(
        optimizer=optimizer,
        scheduler_name=config["scheduler"],
        scheduler_params={
            "factor": config["scheduler_factor"],
            "patience": config["scheduler_patience"],
            "min_lr": config["min_lr"],
        },
    )

    best_acc = 0.0

    search_epochs = max(5, config["epochs"] // 5)

    for epoch in range(search_epochs):
        train_epoch(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            config=config,
        )

        val_loss, _, _, metrics, _ = evaluate(
            model=model,
            loader=val_loader,
            config=config,
        )

        val_acc = metrics["f1" if os.environ.get("TUNE_METRIC") == "f1"
                          else "accuracy"]

        best_acc = max(best_acc, val_acc)

        if scheduler is not None:
            if isinstance(
                scheduler,
                torch.optim.lr_scheduler.ReduceLROnPlateau,
            ):
                scheduler.step(val_loss)

            else:
                scheduler.step()

        trial.report(val_acc, epoch)

        if trial.should_prune():
            model.to(torch.device("cpu"))
            raise optuna.exceptions.TrialPruned()

    model.to(torch.device("cpu"))
    return best_acc


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
        "--checkpoint_dir",
        type=str,
        default="checkpoints/stage0",
    )
    parser.add_argument(
        "--config_out",
        type=str,
        default="checkpoints/stage0/best_stage0_config.json",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
    )

    args = parser.parse_args()

    os.makedirs(args.checkpoint_dir, exist_ok=True)

    set_seed(int(os.environ.get("RUN_SEED", GLOBAL_SEED)))

    labels_dict = load_labels(args.labels_file)

    dataset = PyGGraphDataset(
        encoded_folder=args.encoded_folder,
        labels_dict=labels_dict,
    )

    global_cfg = GlobalConfig()
    stage_cfg = Stage0Config()

    train_set, val_set, test_set = split_dataset(
        dataset=dataset,
        train_frac=global_cfg.train_split,
        val_frac=global_cfg.val_split,
        seed=int(os.environ.get("SPLIT_SEED",
                             os.environ.get("RUN_SEED", GLOBAL_SEED))),
        # SPLIT_SEED fixes the split; RUN_SEED sets the initialisation.
    )

    if os.path.exists(args.config_out):
        with open(args.config_out, "r") as f:
            final_config = json.load(f)
        print(f"\nLoaded config from: {args.config_out}")

    else:
        print("\n===================================")
        print("STAGE 0 OPTUNA SEARCH")
        print("===================================\n")

        study = optuna.create_study(
            direction="maximize",
            study_name="stage0_label_pretraining",
            pruner=optuna.pruners.MedianPruner(
                n_startup_trials=5,
            ),
        )

        study.optimize(
            lambda trial: objective(
                trial,
                dataset,
                train_set,
                val_set,
            ),
            n_trials=OptuneConfig.optuna_trials,
            timeout=OptuneConfig.optuna_timeout,
            show_progress_bar=True,
            gc_after_trial=True,
            catch=(torch.OutOfMemoryError,)
        )

        best_params = study.best_trial.params

        print("\n===================================")
        print("BEST PARAMETERS")
        print("===================================\n")

        for k, v in best_params.items():
            print(f"{k}: {v}")

        print(f"\nBest Validation Accuracy: {study.best_value:.4f}")

        final_config = build_stage0_config(
            global_cfg=global_cfg,
            stage_cfg=stage_cfg,
            tuned_params=best_params,
        )

        with open(args.config_out, "w") as f:
            json.dump(final_config, f, indent=4)

        print(f"\nSaved config to: {args.config_out}")

    train_loader = DataLoader(
        train_set,
        batch_size=final_config["batch_size"],
        shuffle=True,
        collate_fn=collate_graphs_one_by_one,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=final_config["batch_size"],
        shuffle=False,
        collate_fn=collate_graphs_one_by_one,
    )

    test_loader = DataLoader(
        test_set,
        batch_size=final_config["batch_size"],
        shuffle=False,
        collate_fn=collate_graphs_one_by_one,
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

    checkpoint_path = os.path.join(
        args.checkpoint_dir,
        "stage0_best.pt",
    )

    start_epoch = 0
    best_val_loss = float("inf")

    if args.resume and os.path.exists(checkpoint_path):
        checkpoint = load_checkpoint(
            checkpoint_path,
            model,
            optimizer,
        )

        start_epoch = checkpoint["epoch"] + 1
        best_val_loss = checkpoint["val_loss"]

        print(f"\nResumed from epoch {start_epoch}")

    early_stopper = EarlyStopping(
        patience=final_config["early_stop_patience"],
        min_delta=final_config["early_stop_min_delta"],
        mode="min",
    )

    print("\n===================================")
    print("FINAL STAGE 0 TRAINING")
    print("===================================\n")

    for epoch in range(start_epoch, final_config["epochs"]):
        print(f"\nEpoch {epoch + 1}/{final_config['epochs']}")

        train_loss, train_stats = train_epoch(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            config=final_config,
        )

        val_loss, _, _, metrics, val_stats = evaluate(
            model=model,
            loader=val_loader,
            config=final_config,
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

        print(f"LR         : {current_lr:.8f}")

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

    test_loss, test_preds, test_labels, test_metrics, _ = evaluate(
        model=model,
        loader=test_loader,
        config=final_config,
        corrupt=False,
    )

    _, val_preds, val_labels, _, _ = evaluate(
        model=model,
        loader=val_loader,
        config=final_config,
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


if __name__ == "__main__":
    main()

