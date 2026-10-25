import os
import glob
import random
from collections import Counter

import torch
from torch.utils.data import Dataset, Subset

from utils.ablation import filter_pyg_edges, pinned_edge_type_mapping


def _pin_edge_type_mapping(observed):
    pinned = pinned_edge_type_mapping()
    unexpected = sorted(set(observed) - set(pinned))
    if unexpected:
        raise ValueError(f"Encoded graphs contain unknown edge-type codes {unexpected}; expected {pinned}")
    return pinned


class PyGGraphDataset(Dataset):
    def __init__(self, encoded_folder, labels_dict, max_graphs=None, preload=True, normalize_labels=True):
        self.encoded_folder = encoded_folder
        self.labels_dict = labels_dict
        self.preload = preload
        self.normalize_labels = normalize_labels

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

                if data is None:
                    continue

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

        label = self.labels_dict.get(graph_name, 0)

        if self.normalize_labels:
            label = float(label)

        data.graph_name = graph_name

        data.y = torch.tensor([label], dtype=torch.float32)

        if not hasattr(data, "x"):
            raise ValueError(f"{graph_name} missing node features")

        if not hasattr(data, "edge_index"):
            raise ValueError(f"{graph_name} missing edge_index")

        if not hasattr(data, "edge_type"):
            data.edge_type = torch.zeros(data.edge_index.size(1), dtype=torch.long)

        # Relation ablation (Table VIII); no-op unless DROP_RELATIONS is set.

        data = filter_pyg_edges(data)

        self._edge_type_mapping.update([str(t) for t in data.edge_type.tolist()])

        data.num_nodes = data.x.size(0)
        data.num_edges = data.edge_index.size(1)

        data.node_mask = torch.zeros(data.num_nodes, dtype=torch.bool)

        data.edge_mask = torch.zeros(data.num_edges, dtype=torch.bool)

        return data

    def compute_stats(self):
        if len(self.dataset) == 0:
            return

        labels = []
        node_counts = []
        edge_counts = []

        edge_counter = Counter()

        for data in self.dataset:
            labels.append(int(data.y.item()))

            node_counts.append(data.num_nodes)
            edge_counts.append(data.num_edges)

            for t in data.edge_type.tolist():
                edge_counter[str(t)] += 1

        self._edge_type_mapping = _pin_edge_type_mapping(self._edge_type_mapping)

        self._stats = {
            "num_graphs": len(self.dataset),
            "positive_graphs": sum(labels),
            "negative_graphs": len(labels) - sum(labels),
            "avg_nodes": sum(node_counts) / len(node_counts),
            "avg_edges": sum(edge_counts) / len(edge_counts),
            "edge_distribution": dict(edge_counter),
            "edge_types": self._edge_type_mapping,
        }

    def __len__(self):
        if self.preload:
            return len(self.dataset)

        return len(self.file_paths)

    def __getitem__(self, idx):
        if self.preload:
            return self.dataset[idx]

        return self.load_graph(self.file_paths[idx])

    @property
    def edge_type_mapping(self):
        return self._edge_type_mapping

    @property
    def stats(self):
        return self._stats


def split_dataset(dataset, train_frac=0.7, val_frac=0.15, seed=22, stratified=True):
    from utils.grouped_split import grouped_split_dataset
    return grouped_split_dataset(dataset, train_frac=train_frac, val_frac=val_frac, seed=seed)


def collate_graphs_one_by_one(batch):
    return batch

