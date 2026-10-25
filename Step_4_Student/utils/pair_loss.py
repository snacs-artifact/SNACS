import json
import os
import random

import torch
import torch.nn.functional as F


class PairBank:
    def __init__(self, pairs_json, encoded_folder, device, log=print):
        self.device = device
        pairs = json.load(open(pairs_json))
        self.pairs = []
        self.cache = {}
        missing = 0
        for p in pairs:
            a, b = p["vuln"], p["safe"]
            pa = os.path.join(encoded_folder, f"{a}.pt")
            pb = os.path.join(encoded_folder, f"{b}.pt")
            if not (os.path.exists(pa) and os.path.exists(pb)):
                missing += 1
                continue
            for n, path in ((a, pa), (b, pb)):
                if n not in self.cache:
                    self.cache[n] = torch.load(path, map_location="cpu",
                                               weights_only=False)
            self.pairs.append((a, b))
        log(f"[pair] {len(self.pairs)} usable pairs "
            f"({missing} skipped for missing encodings), "
            f"{len(self.cache)} graphs cached")
        self._order = []

    def __len__(self):
        return len(self.pairs)

    def sample(self, n):
        out = []
        for _ in range(min(n, len(self.pairs))):
            if not self._order:
                self._order = list(range(len(self.pairs)))
                random.shuffle(self._order)
            out.append(self.pairs[self._order.pop()])
        return out


def pair_ranking_loss(model, bank, K, margin=0.2, n_sample=16):
    if len(bank) == 0:
        return torch.zeros((), device=bank.device)
    losses = []
    for a, b in bank.sample(n_sample):
        s = []
        for name in (a, b):
            d = bank.cache[name].to(bank.device)
            from utils.text_features import forward_with_text
            h = forward_with_text(model, d, K=K, name=name)
            s.append(model.graph_score(h).view(()))
        # s[0] = unguarded (vulnerable), s[1] = guarded (safe)
        losses.append(F.relu(margin - (s[0] - s[1])))
    return torch.stack(losses).mean()

