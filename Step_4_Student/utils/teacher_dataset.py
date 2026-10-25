import os
import glob
import json
import random
from collections import Counter

import torch
from torch.utils.data import Dataset, Subset

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Step_3_Teacher"))
from teacher_taint_engine import SDGTaintEngine
from utils.ablation import (
    assert_teacher_cache_matches,
    filter_pyg_edges,
    filter_sdg_edges,
)
from utils.dataset import _pin_edge_type_mapping


class PyGGraphDataset(Dataset):
    def __init__(
        self,
        encoded_folder,
        labels_dict,
        sdg_folder,
        use_teacher=True,
        use_trajectory=True,
        use_edge_labels=True,
        cache_teacher=True,
        teacher_cache_dir="teacher_cache",
        preload=True,
        max_graphs=None,
        max_teacher_iters=8,
        node_mask_ratio=0.0,
        edge_mask_ratio=0.0,
        feature_mask_ratio=0.0,
    ):
        self.encoded_folder = encoded_folder
        self.labels_dict = labels_dict

        self.sdg_folder = sdg_folder

        self.use_teacher = use_teacher
        self.use_trajectory = use_trajectory
        self.use_edge_labels = use_edge_labels

        self.cache_teacher = cache_teacher
        self.teacher_cache_dir = teacher_cache_dir

        self.preload = preload
        self.max_teacher_iters = max_teacher_iters

        self.node_mask_ratio = node_mask_ratio
        self.edge_mask_ratio = edge_mask_ratio
        self.feature_mask_ratio = feature_mask_ratio

        os.makedirs(self.teacher_cache_dir, exist_ok=True)

        assert_teacher_cache_matches(self.teacher_cache_dir)

        self.dataset = []
        self.file_paths = []

        self._edge_type_mapping = set()
        self._stats = {}

        file_paths = sorted(glob.glob(os.path.join(encoded_folder, "*.pt")))

        if max_graphs is not None:
            file_paths = file_paths[:max_graphs]

        self.file_paths = file_paths

        if preload:
            for file_path in self.file_paths:
                data = self.load_graph(file_path)

                if data is not None:
                    self.dataset.append(data)

        self.compute_stats()

    def load_graph(self, file_path):
        try:
            data = torch.load(file_path, weights_only=False, map_location="cpu")

        except Exception as e:
            print(f"[DATASET ERROR] Failed loading: {file_path}")
            print(e)

            return None

        graph_name = os.path.basename(file_path).replace(".pt", "")

        data.graph_name = graph_name

        data.y = torch.tensor([float(self.labels_dict.get(graph_name, 0))], dtype=torch.float32)

        if not hasattr(data, "x"):
            raise ValueError(f"{graph_name} missing node features")

        if not hasattr(data, "edge_index"):
            raise ValueError(f"{graph_name} missing edge_index")

        if not hasattr(data, "edge_type"):
            data.edge_type = torch.zeros(data.edge_index.size(1), dtype=torch.long)

        # Relation ablation (Table VIII), student side; no-op unless DROP_RELATIONS is set.

        data = filter_pyg_edges(data)

        data.num_nodes = data.x.size(0)
        data.num_edges = data.edge_index.size(1)

        self._edge_type_mapping.update([str(t) for t in data.edge_type.tolist()])

        data.masked_x = data.x.clone()

        data.node_mask = torch.zeros(data.num_nodes, dtype=torch.bool)

        data.edge_mask = torch.zeros(data.num_edges, dtype=torch.bool)

        data.y_node = torch.zeros(data.num_nodes, 2)

        data.y_edge = torch.zeros(data.num_edges)

        data.y_graph_teacher = torch.zeros(1)

        data.y_node_trajectory = []

        return data

    def run_teacher(self, graph_name):
        cache_path = os.path.join(self.teacher_cache_dir, graph_name + ".pt")

        if self.cache_teacher and os.path.exists(cache_path):
            return torch.load(cache_path, weights_only=False, map_location="cpu")

        sdg_path = os.path.join(self.sdg_folder, graph_name + ".json")

        with open(sdg_path, "r") as f:
            graph_json = json.load(f)

        # Relation ablation (Table VIII), teacher side: the teacher must not use a
        # relation that the student cannot see.

        graph_json = filter_sdg_edges(graph_json)

        engine = SDGTaintEngine(graph_json)

        out = engine.run(max_iters=self.max_teacher_iters)

        if self.cache_teacher:
            torch.save(out, cache_path)

        return out

    def build_node_labels(self, graph_json, teacher_output, num_nodes):
        y_node = torch.zeros(num_nodes, 2)

        node_ids = [node["id"] for node in graph_json["nodes"]]

        if len(node_ids) != num_nodes:
            raise ValueError("Mismatch between SDG nodes and PyG nodes.\n" "Ensure encoding preserves node ordering.")

        node_map = {nid: i for i, nid in enumerate(node_ids)}

        teacher_nodes = teacher_output["y_node"]

        for nid, info in teacher_nodes.items():
            if nid not in node_map:
                continue

            idx = node_map[nid]

            y_node[idx, 0] = float(info.get("tainted", 0.0))

            y_node[idx, 1] = float(info.get("sanitized", 0.0))

        return y_node

    def build_edge_labels(self, data, teacher_output):
        y_edge = torch.zeros(data.num_edges)

        if "edge_history" not in teacher_output:
            return y_edge

        edge_history = teacher_output["edge_history"]

        # Placeholder edge target (0.1 on every edge if any edge was active). The
        # model has no predict_edges method, so the loss on this target never runs.

        if len(edge_history) == 0:
            return y_edge

        active_edges = set()

        for step in edge_history:
            for edge in step:
                if edge.get("active", False):
                    src = edge.get("from")
                    dst = edge.get("to")

                    active_edges.add((src, dst))

        if len(active_edges) > 0:
            y_edge += 0.1

        return y_edge.clamp(0, 1)

    def apply_masking(self, data):
        if self.node_mask_ratio > 0:
            num_mask = max(1, int(data.num_nodes * self.node_mask_ratio))

            idx = torch.randperm(data.num_nodes)[:num_mask]

            data.node_mask[idx] = True

        if self.feature_mask_ratio > 0:
            num_mask = max(1, int(data.num_nodes * self.feature_mask_ratio))

            idx = torch.randperm(data.num_nodes)[:num_mask]

            data.masked_x[idx] = 0

            data.node_mask[idx] = True

        if self.edge_mask_ratio > 0:
            num_mask = max(1, int(data.num_edges * self.edge_mask_ratio))

            idx = torch.randperm(data.num_edges)[:num_mask]

            data.edge_mask[idx] = True

    def __getitem__(self, idx):
        if self.preload:
            data = self.dataset[idx]

        else:
            data = self.load_graph(self.file_paths[idx])

        # clone because masking is mutable
        data = data.clone()

        self.apply_masking(data)

        if not self.use_teacher:
            return data

        teacher_output = self.run_teacher(data.graph_name)

        sdg_path = os.path.join(self.sdg_folder, data.graph_name + ".json")

        with open(sdg_path, "r") as f:
            graph_json = json.load(f)

        data.y_node = self.build_node_labels(graph_json, teacher_output, data.num_nodes)

        data.y_graph_teacher = torch.tensor([float(teacher_output["y_graph"])], dtype=torch.float32)

        if self.use_edge_labels:
            data.y_edge = self.build_edge_labels(data, teacher_output)

        if self.use_trajectory:
            data.y_node_trajectory = teacher_output.get("history", [])

        return data

    def compute_stats(self):
        if len(self.dataset) == 0:
            return

        labels = []
        nodes = []
        edges = []

        edge_counter = Counter()

        for data in self.dataset:
            labels.append(int(data.y.item()))

            nodes.append(data.num_nodes)
            edges.append(data.num_edges)

            for t in data.edge_type.tolist():
                edge_counter[str(t)] += 1

        self._edge_type_mapping = _pin_edge_type_mapping(self._edge_type_mapping)

        self._stats = {
            "num_graphs": len(self.dataset),
            "positive_graphs": sum(labels),
            "negative_graphs": len(labels) - sum(labels),
            "avg_nodes": sum(nodes) / len(nodes),
            "avg_edges": sum(edges) / len(edges),
            "edge_distribution": dict(edge_counter),
            "edge_types": self._edge_type_mapping,
        }

    @property
    def edge_type_mapping(self):
        return self._edge_type_mapping

    @property
    def stats(self):
        return self._stats

    def __len__(self):
        if self.preload:
            return len(self.dataset)

        return len(self.file_paths)


def split_dataset(dataset, train_frac=0.7, val_frac=0.15, seed=22, stratified=True):
    from utils.grouped_split import grouped_split_dataset
    return grouped_split_dataset(dataset, train_frac=train_frac, val_frac=val_frac, seed=seed)


def collate_graphs_one_by_one(batch):
    return batch

