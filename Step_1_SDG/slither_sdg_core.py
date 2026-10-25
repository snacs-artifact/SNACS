# slither_sdg_core.py
import re
import os
import subprocess
import json
from collections import defaultdict, deque
from slither.slither import Slither
from slither.core.cfg.node import NodeType
from slither.slithir.operations import (
    OperationWithLValue,
    HighLevelCall,
    LowLevelCall,
    InternalCall,
    LibraryCall,
    Binary,
    Unary,
)
from packaging import version as pkg_version


# ---------------- Solidity helpers ----------------
def get_solidity_version(file_path: str):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    matches = re.findall(r"pragma\s+solidity\s+([^;<]+)[;<]", content)
    versions = []
    for match in matches:
        found = re.findall(r"(\d+\.\d+\.\d+)", match)
        if not found:
            found = [v + ".0" for v in re.findall(r"(\d+\.\d+)", match)]
        versions.extend(found)
    if not versions:
        return "0.8.20"
    v = max(versions, key=pkg_version.parse)
    if pkg_version.parse(v) < pkg_version.parse("0.4.0"):
        return "0.4.0"
    if pkg_version.parse(v) > pkg_version.parse("0.8.29"):
        return "0.8.29"
    return v


def set_solc_version(ver):
    subprocess.run(["solc-select", "use", ver], check=True, capture_output=True, text=True)


# ---------------- IR / CFG helpers ----------------
AUTH_GUARD_CALLS = {"onlyOwner", "hasRole", "_checkRole", "onlyRole"}


def norm_var(v):
    v = v.replace("this.", "")
    for sep in ["(", "[", "."]:
        if sep in v:
            v = v.split(sep, 1)[0]
    return v.strip()


def ir_reads(ir):
    return [norm_var(str(v)) for v in getattr(ir, "read", [])]


def ir_write(ir):
    return norm_var(str(ir.lvalue)) if isinstance(ir, OperationWithLValue) and ir.lvalue else None


def is_require(ir):
    s = str(ir).lower()
    return any(k in s for k in ("require", "assert", "revert"))


def is_guard_ir(ir):
    return is_require(ir) or any(k in str(ir) for k in AUTH_GUARD_CALLS)


def ir_reads_tx_origin(ir):
    if hasattr(ir, "read") and ir.read:
        return any(str(v) == "tx.origin" for v in ir.read)
    return False


def is_arithmetic(ir):
    return isinstance(ir, (Binary, Unary))


def is_call_ir(ir):
    return isinstance(ir, (HighLevelCall, LowLevelCall, InternalCall, LibraryCall))


def is_external_call(ir):
    return isinstance(ir, (HighLevelCall, LowLevelCall))


def is_delegatecall(ir):
    return isinstance(ir, LowLevelCall) and "delegatecall" in str(ir).lower()


def reads_block_info(ir):
    label = str(ir)
    return "block.timestamp" in label or "block.number" in label


def compute_cfg_depth(fn):
    depths = {}
    q = deque([(fn.entry_point, 0)])
    visited = set()
    while q:
        node, d = q.popleft()
        if node in visited:
            continue
        visited.add(node)
        depths[node] = d
        for s in node.sons:
            q.append((s, d + 1))
    return depths


def _src_of(cfg_node):
    """(byte_start, byte_length) of a CFG node in its source file, or None."""
    sm = getattr(cfg_node, "source_mapping", None)
    if sm is None:
        return None
    st = getattr(sm, "start", None)
    ln = getattr(sm, "length", None)
    if st is None or ln is None:
        return None
    return (st, ln)


# ---------------- SDG node/edge helpers ----------------
def create_node(graph, node_id, label, contract, function, features=None,
                semantic=None, is_constructor=False, src=None):
    """`is_constructor` and `src` are recorded in META, deliberately not in
    `features` or `semantic`: the encoder reads only those two dicts, so
    provenance can be carried without perturbing the learned node representation.

    `src` is (byte_offset, byte_length) of the statement in the original .sol
    file, used by v7 to recover the SOURCE text for a pretrained code model.
    CodeBERT was pretrained on Solidity source, not on SlithIR serialisation, so
    embedding `label` directly would be off-distribution."""
    meta = {"contract": contract, "function": function,
            "is_constructor": bool(is_constructor)}
    if src is not None:
        meta["src_start"], meta["src_len"] = int(src[0]), int(src[1])
    graph["nodes"].append(
        {
            "id": node_id,
            "label": label,
            "meta": meta,
            "features": features or {},
            "semantic": semantic or {},
        }
    )


def create_node_with_features(
    modules,
    graph,
    contract,
    merged_semantic,
    state_vars,
    is_upgradeable,
    function,
    is_entry,
    cfg_node,
    ir,
    nid,
    label=None,
):
    merged_features = {}
    for mod in modules:
        mod_features, mod_semantics = mod(
            ir,
            cfg_node,
            function,
            contract,
            nid,
            is_entry=is_entry,
            state_vars=state_vars,
            is_upgradeable=is_upgradeable,
        )
        merged_features.update(mod_features or {})
        merged_semantic.update(mod_semantics or {})

    create_node(
        graph, nid, label or str(ir), contract.name, getattr(function, "name", None),
        merged_features, merged_semantic,
        is_constructor=bool(getattr(function, "is_constructor", False)
                            or getattr(function, "is_constructor_variables", False)),
        src=_src_of(cfg_node),
    )


def add_edge(graph, from_id, to_id, edge_type, **kwargs):
    edge = {"from": from_id, "to": to_id, "type": edge_type}
    edge.update(kwargs)
    graph["edges"].append(edge)


# ---------------- SDG orchestration ----------------
def slither_analyze(file_path, modules, solidity_version = None):
    """
    Core SDG orchestration with multiple vulnerability modules.

    modules: list of dicts with keys:
        - "node_callback": fn(ir, cfg_node, function, contract, node_id, cfg_depths, is_entry, state_vars, is_upgradeable) -> (features, semantic)
        - "edge_callback": fn(cfg_node_to_ir_ids, function, node_ids, graph)
    """
    # set_solc_version(solidity_version or get_solidity_version(file_path))
    sl = Slither(file_path)
    graph = {"nodes": [], "edges": []}
    node_id_counter = 0
    node_ids = {}

    for contract in sl.contracts:
        state_vars = {sv.name for sv in contract.state_variables}

        is_upgradeable = any(
            "delegatecall" in str(ir).lower() for f in contract.functions for n in f.nodes for ir in (n.irs or [])
        )

        # --- Add contract node ---
        contract_node_id = f"n{node_id_counter}"
        node_id_counter += 1
        semantic = {"node_type": "contract", "cfg_depth": 0, "function_visibility": None}
        create_node_with_features(
            modules,
            graph,
            contract,
            semantic,
            state_vars,
            is_upgradeable,
            None,
            False,
            contract,
            contract,
            contract_node_id,
            f"Contract:{contract.name}",
        )

        # Cross-function state read/write tracking (contract scope) for SD edges.
        sd_writes = defaultdict(list)
        sd_reads = defaultdict(list)

        for function in contract.functions_declared:
            if not function.is_implemented:
                continue
            cfg_depths = compute_cfg_depth(function)
            is_entry = function.visibility in {"public", "external"}

            # --- Add function node ---
            function_node_id = f"n{node_id_counter}"
            node_id_counter += 1
            semantic = {
                "node_type": "function",
                "cfg_depth": 0,
                "function_visibility": function.visibility,
            }
            create_node_with_features(
                modules,
                graph,
                contract,
                semantic,
                state_vars,
                is_upgradeable,
                function,
                is_entry,
                function,
                function,
                function_node_id,
                f"Function:{function.name}",
            )
            # Connect function node to contract node
            add_edge(graph, contract_node_id, function_node_id, "contains")

            cfgnode_to_irnodeids = {}

            # --- Statement nodes ---
            for cfg_node in function.nodes:
                ids = []
                for idx, ir in enumerate(cfg_node.irs or []):
                    nid = f"n{node_id_counter}"
                    node_id_counter += 1
                    ids.append(nid)
                    write = ir_write(ir)

                    # Merge features/semantic from all modules
                    merged_semantic = {
                        "node_type": (
                            "assignment"
                            if write
                            else (
                                "call"
                                if is_call_ir(ir)
                                else "conditional" if cfg_node.type in {NodeType.IF, NodeType.IFLOOP} else "other"
                            )
                        ),
                        "cfg_depth": cfg_depths.get(cfg_node, 0),
                        "function_visibility": function.visibility,
                    }
                    create_node_with_features(
                        modules,
                        graph,
                        contract,
                        merged_semantic,
                        state_vars,
                        is_upgradeable,
                        function,
                        is_entry,
                        cfg_node,
                        ir,
                        nid,
                    )
                    node_ids[(function.name, cfg_node, idx)] = nid

                    # Track state-variable reads/writes for cross-function SD edges.
                    # (state var written in one function and read in another = storage flow)
                    for _rv in ir_reads(ir):
                        if _rv in state_vars:
                            sd_reads[_rv].append((nid, function.name))
                    if write and write in state_vars:
                        sd_writes[write].append((nid, function.name))
                cfgnode_to_irnodeids[cfg_node] = ids

            # --- Build edges ---
            # SEQ edges
            for ids in cfgnode_to_irnodeids.values():
                for a, b in zip(ids[:-1], ids[1:]):
                    add_edge(graph, a, b, "seq")
            # CF edges
            for src_node in function.nodes:
                src_ids = cfgnode_to_irnodeids.get(src_node, [])
                if not src_ids:
                    continue
                src_last = src_ids[-1]
                for child in src_node.sons:
                    dst_ids = cfgnode_to_irnodeids.get(child, [])
                    if dst_ids:
                        add_edge(graph, src_last, dst_ids[0], "cf")
            # DD edges (def-use)
            last_def = {}
            for cfg_node in function.nodes:
                for i, ir in enumerate(cfg_node.irs or []):
                    cur_id = node_ids.get((function.name, cfg_node, i))
                    if not cur_id:
                        continue
                    for rv in ir_reads(ir):
                        if rv in last_def:
                            add_edge(graph, last_def[rv], cur_id, "dd")
                    dv = ir_write(ir)
                    if dv:
                        last_def[dv] = cur_id
            # GD edges (guards/modifiers)
            #
            # Guard dependence = every operation FORWARD-REACHABLE from the guard
            # through CFG successors, within this function. For an authorization
            # `require(...)` the continuation after the require IS the guarded
            # region, which is the property the sanitization-aware teacher relies
            # on when it credits a sink with a clean score.
            #
            # Previously the frontier was seeded with `cfg_node.sons` but never
            # expanded (`q.extend(cur.sons)` was missing), so gd reached only the
            # guard's IMMEDIATE successors. Measured effect: an inserted
            # authorization guard had a gd edge to a sensitive sink in just 20.3%
            # of cases, and 79.1% of sinks inside a guarded function never
            # received guard evidence at all.
            MAX_GD = 2000
            gd_seen = set()
            for cfg_node in function.nodes:
                guard_indices = [i for i, ir in enumerate(cfg_node.irs or []) if is_guard_ir(ir)]
                for gi in guard_indices:
                    guard_id = node_ids.get((function.name, cfg_node, gi))
                    if not guard_id:
                        continue

                    # (a) the remaining IRs of the guard's own CFG node are already
                    #     past the guard, so they are part of the guarded region
                    for tid in cfgnode_to_irnodeids.get(cfg_node, [])[gi + 1:]:
                        key = (guard_id, tid)
                        if key not in gd_seen:
                            gd_seen.add(key)
                            add_edge(graph, guard_id, tid, "gd")

                    # (b) transitive forward CFG closure, function-local by
                    #     construction: `function.nodes` never leaves the function
                    q = deque(cfg_node.sons)
                    visited = set()
                    steps = 0
                    while q and steps < MAX_GD:
                        cur = q.popleft()
                        if cur in visited:
                            continue
                        visited.add(cur)
                        steps += 1
                        for tid in cfgnode_to_irnodeids.get(cur, []):
                            key = (guard_id, tid)
                            if key not in gd_seen:
                                gd_seen.add(key)
                                add_edge(graph, guard_id, tid, "gd")
                        q.extend(cur.sons)          # <-- the missing expansion

        # SD edges (contract scope): a state variable written in one function and
        # read in another = cross-function storage flow. Built AFTER the per-function
        # loop so writes/reads from all functions are visible.
        SD_MAX = 4000
        sd_seen = set()
        sd_added = 0
        for _var, _writes in sd_writes.items():
            for _wid, _wfn in _writes:
                for _rid, _rfn in sd_reads.get(_var, []):
                    if _wfn != _rfn and (_wid, _rid) not in sd_seen:
                        sd_seen.add((_wid, _rid))
                        add_edge(graph, _wid, _rid, "sd", slot=_var)
                        sd_added += 1
            if sd_added >= SD_MAX:
                break

    # --- Save output ---
    out_dir = "sdg"
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(file_path))[0]
    out_file = os.path.join(out_dir, f"{base}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    print(f"[+] SDG saved to {out_file}")
