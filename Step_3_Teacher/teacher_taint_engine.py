from collections import defaultdict
import math
import copy
import os


EDGE_WEIGHTS = {
    # data dependency
    "dd": 1.0,
    # state dependency (SD_EDGE_WEIGHT; 0.7 for the final model)
    "sd": float(os.environ.get("SD_EDGE_WEIGHT", 0.9)),
    # control flow
    "cf": 0.55,
    # sequential
    "seq": 0.30,
    # guard dependency
    "gd": 0.70,
    # hierarchy
    "contains": 0.10,
}


BASE_DECAY = 0.92
CONTROL_FLOW_DECAY = 0.75


SANITIZER_STRENGTH = 0.85
REENTRANCY_GUARD_STRENGTH = 0.90
LIMIT_CHECK_STRENGTH = 0.75


EXTERNAL_CALL_RISK = 1.30
DELEGATECALL_RISK = 1.50
ORACLE_RISK = 1.20
FINANCIAL_RISK = 1.25
PRIVILEGED_WRITE_RISK = 1.35


EPS = 1e-6

# TAINT_ONLY_TEACHER=1 removes the clean channel: no sanitizer credit, no guard
# attenuation, sink risk mu*t (Table IX, taint-only row).

TAINT_ONLY = os.environ.get("TAINT_ONLY_TEACHER", "0") == "1"

# TEACHER_NO_LIMIT_CHECKS=1 stops limit checks from counting as sanitizers
# (an experiment, not used in the paper).
NO_LIMIT_SANITIZER = os.environ.get("TEACHER_NO_LIMIT_CHECKS", "0") == "1"


class TaintState:
    def __init__(self, taint=0.0, clean=0.0, confidence=0.0, depth=0):
        self.taint = float(taint)
        self.clean = float(clean)

        self.confidence = float(confidence)

        self.depth = int(depth)

    def copy(self):
        return TaintState(taint=self.taint, clean=self.clean, confidence=self.confidence, depth=self.depth)

    def to_dict(self):
        return {
            "tainted": float(self.taint),
            "sanitized": float(self.clean),
            "confidence": float(self.confidence),
            "depth": int(self.depth),
        }


class SDGTaintEngine:
    def __init__(self, graph_json):
        self.graph_json = graph_json

        self.nodes = {n["id"]: n for n in graph_json["nodes"]}

        self.edges = graph_json["edges"]

        self.out_edges = defaultdict(list)
        self.in_edges = defaultdict(list)

        for edge in self.edges:
            self.out_edges[edge["from"]].append(edge)
            self.in_edges[edge["to"]].append(edge)

        self.state = {nid: TaintState() for nid in self.nodes}

    def features(self, node):
        return node.get("features", {})

    def semantic(self, node):
        return node.get("semantic", {})

    def is_source(self, node):
        f = self.features(node)

        return any(
            [
                f.get("uses_tx_origin", False),
                f.get("uses_msg_sender", False),
                f.get("tainted_by_oracle", False),
                f.get("call_target_user_controlled", False),
                f.get("reads_block_info", False),
            ]
        )

    def is_sink(self, node):
        f = self.features(node)

        # Constructor code runs only at deployment, so it is never a sink.
        if (node.get("meta") or {}).get("is_constructor", False):
            return False

        return any(
            [
                f.get("is_external_call", False),
                f.get("is_delegatecall", False),
                f.get("writes_privileged_state", False),
                f.get("writes_sensitive_state", False),
                f.get("is_transfer", False),
                f.get("is_liquidation", False),
                f.get("calls_financial_function", False),
            ]
        )

    def is_sanitizer(self, node):
        f = self.features(node)
        s = self.semantic(node)

        guard_kind = s.get("guard_kind")

        checks = [
            f.get("is_require", False),
            f.get("reentrancy_guard_present", False),
            f.get("is_assert", False),
            guard_kind in ["auth", "auth_weak", "ownership", "role", "reentrancy"],
        ]
        if not NO_LIMIT_SANITIZER:                 # default: limit checks count
            checks.append(f.get("has_limit_checks", False))
        return any(checks)

    def risk_multiplier(self, node):
        f = self.features(node)

        risk = 1.0

        if f.get("is_external_call", False):
            risk *= EXTERNAL_CALL_RISK

        if f.get("is_delegatecall", False):
            risk *= DELEGATECALL_RISK

        if f.get("tainted_by_oracle", False):
            risk *= ORACLE_RISK

        if f.get("calls_financial_function", False):
            risk *= FINANCIAL_RISK

        if f.get("writes_privileged_state", False):
            risk *= PRIVILEGED_WRITE_RISK

        return risk

    def has_guard(self, node_id):
        for edge in self.in_edges[node_id]:
            if edge["type"] != "gd":
                continue

            src = edge["from"]

            if self.is_sanitizer(self.nodes[src]):
                return True

        return False

    def initialize(self):
        for nid, node in self.nodes.items():
            state = TaintState()

            if self.is_source(node):
                state.taint = 1.0
                state.confidence = 1.0

            if self.is_sanitizer(node) and not TAINT_ONLY:
                state.clean = 0.5

            self.state[nid] = state

    def step(self):
        new_state = {nid: self.state[nid].copy() for nid in self.nodes}

        changed = False

        for edge in self.edges:
            src_id = edge["from"]
            dst_id = edge["to"]

            etype = edge["type"]

            if etype not in EDGE_WEIGHTS:
                continue

            src_node = self.nodes[src_id]
            dst_node = self.nodes[dst_id]

            src_state = self.state[src_id]
            dst_state = new_state[dst_id]

            weight = EDGE_WEIGHTS[etype]

            decay = BASE_DECAY

            if etype == "cf":
                decay *= CONTROL_FLOW_DECAY

            propagated_taint = src_state.taint * weight * decay

            propagated_clean = src_state.clean * weight * decay

            propagated_taint *= 1.0 / (1.0 + 0.05 * src_state.depth)

            if self.is_sanitizer(src_node) and not TAINT_ONLY:
                sanitizer_strength = SANITIZER_STRENGTH

                f = self.features(src_node)

                if f.get("reentrancy_guard_present", False):
                    sanitizer_strength = max(sanitizer_strength, REENTRANCY_GUARD_STRENGTH)

                if f.get("has_limit_checks", False):
                    sanitizer_strength = max(sanitizer_strength, LIMIT_CHECK_STRENGTH)

                clean_gain = propagated_taint * sanitizer_strength

                propagated_clean = max(propagated_clean, clean_gain)

                propagated_taint *= 1.0 - sanitizer_strength

            if self.has_guard(dst_id) and not TAINT_ONLY:
                propagated_clean = max(propagated_clean, propagated_taint * 0.8)

                propagated_taint *= 0.2

            propagated_taint *= self.risk_multiplier(dst_node)

            propagated_taint = min(propagated_taint, 1.0)

            propagated_clean = min(propagated_clean, 1.0)

            updated_taint = max(dst_state.taint, propagated_taint)

            updated_clean = max(dst_state.clean, propagated_clean)

            updated_confidence = max(dst_state.confidence, src_state.confidence * weight)

            if abs(updated_taint - dst_state.taint) > EPS or abs(updated_clean - dst_state.clean) > EPS:
                dst_state.taint = updated_taint
                dst_state.clean = updated_clean

                dst_state.confidence = updated_confidence

                dst_state.depth = min(dst_state.depth + 1, 100)

                changed = True

        self.state = new_state

        return changed

    def snapshot(self):
        return {nid: self.state[nid].to_dict() for nid in self.nodes}

    def compute_edge_labels(self):
        labels = []

        for edge in self.edges:
            src = edge["from"]
            dst = edge["to"]

            etype = edge["type"]

            weight = EDGE_WEIGHTS.get(etype, 0.0)

            src_state = self.state[src]

            contribution = src_state.taint * weight * src_state.confidence

            labels.append(
                {
                    "from": src,
                    "to": dst,
                    "type": etype,
                    "label": float(min(contribution, 1.0)),
                    "active": bool(contribution > 0.1),
                }
            )

        return labels

    def compute_graph_label(self):
        max_risk = 0.0

        for nid, node in self.nodes.items():
            if not self.is_sink(node):
                continue

            state = self.state[nid]

            clean_factor = 1.0 if TAINT_ONLY else (1.0 - state.clean)

            risk = state.taint * clean_factor * self.risk_multiplier(node)

            max_risk = max(max_risk, risk)

        return float(min(max_risk, 1.0))

    def extract_paths(self):
        paths = []

        for nid, node in self.nodes.items():
            if not self.is_sink(node):
                continue

            state = self.state[nid]

            if state.taint < 0.10:
                continue

            path = self.backtrack_path(nid)

            if len(path) == 0:
                continue

            paths.append({"sink": nid, "risk": float(state.taint * (1.0 - state.clean)), "path": path})

        return paths

    def backtrack_path(self, target):
        path = [target]

        current = target

        visited = set()

        while True:
            if current in visited:
                break

            visited.add(current)

            best_prev = None
            best_score = 0.0

            for edge in self.in_edges[current]:
                etype = edge["type"]

                if etype not in EDGE_WEIGHTS:
                    continue

                src = edge["from"]

                score = self.state[src].taint * EDGE_WEIGHTS[etype]

                if score > best_score:
                    best_score = score
                    best_prev = src

            if best_prev is None:
                break

            path.append(best_prev)

            current = best_prev

            if self.is_source(self.nodes[current]):
                break

        return list(reversed(path))

    def run(self, max_iters=10):
        self.initialize()

        history = []
        edge_history = []

        for _ in range(max_iters):
            history.append(copy.deepcopy(self.snapshot()))

            edge_history.append(copy.deepcopy(self.compute_edge_labels()))

            changed = self.step()

            if not changed:
                break

        y_node = {
            nid: {
                "tainted": float(self.state[nid].taint),
                "sanitized": float(self.state[nid].clean),
                "confidence": float(self.state[nid].confidence),
            }
            for nid in self.nodes
        }

        y_graph = self.compute_graph_label()

        y_edge = self.compute_edge_labels()

        paths = self.extract_paths()

        return {
            "history": history,
            "edge_history": edge_history,
            "y_node": y_node,
            "y_edge": y_edge,
            "y_graph": y_graph,
            "paths": paths,
        }

