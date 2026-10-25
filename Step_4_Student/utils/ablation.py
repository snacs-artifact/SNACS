import json
import os

# Relation id == index in this list. Fixed globally by the encoder
# (Step_2_Preprocessing/sdg_encoder.py) so codes are stable across
# graphs even when a relation is absent from a particular contract.
RELATION_NAMES = ["cf", "contains", "dd", "gd", "sd", "seq"]

LOSS_TERMS = {
    "graph_teacher": "use_teacher_graph_loss",  # lambda_g  MSE(y_hat, y_graph)
    "node": "use_teacher_node_loss",            # lambda_n  L_node
    "traj": "use_traj_loss",                    # lambda_r  L_traj
    "node_rec": "use_node_rec_loss",            # lambda_x  L_node-rec
    "link": "use_link_loss",                    # lambda_e  L_link
}


def _env_list(var):
    raw = os.environ.get(var, "").strip()
    if not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def dropped_relations():
    names = _env_list("DROP_RELATIONS")
    bad = [n for n in names if n not in RELATION_NAMES]
    if bad:
        raise ValueError(f"DROP_RELATIONS contains unknown relation(s) {bad}; expected from {RELATION_NAMES}")
    return names


def dropped_ids():
    return {RELATION_NAMES.index(n) for n in dropped_relations()}


def pinned_edge_type_mapping():
    return [str(i) for i in range(len(RELATION_NAMES))]


def arm_tag():
    names = dropped_relations()
    return ("no" + "".join(names)) if names else "full"


def filter_pyg_edges(data):
    drop = dropped_ids()
    if not drop or data.edge_index.size(1) == 0:
        return data

    import torch

    keep = torch.ones(data.edge_type.numel(), dtype=torch.bool)
    for rid in drop:
        keep &= data.edge_type != rid

    data.edge_index = data.edge_index[:, keep]
    data.edge_type = data.edge_type[keep]
    return data


def filter_sdg_edges(graph_json):
    drop = {RELATION_NAMES[i] for i in dropped_ids()}
    if not drop:
        return graph_json
    out = dict(graph_json)
    out["edges"] = [e for e in graph_json["edges"] if e["type"] not in drop]
    return out


_SIGNATURE_DEFAULTS = {
    "drop_relations": [],
    "sd_edge_weight": "0.9",
    "taint_only_teacher": "0",
}


def teacher_cache_signature():
    return {
        "drop_relations": sorted(dropped_relations()),
        "sd_edge_weight": os.environ.get("SD_EDGE_WEIGHT", _SIGNATURE_DEFAULTS["sd_edge_weight"]),
        "taint_only_teacher": os.environ.get("TAINT_ONLY_TEACHER", _SIGNATURE_DEFAULTS["taint_only_teacher"]),
    }


def _normalise_signature(sig):
    out = dict(_SIGNATURE_DEFAULTS)
    out.update(sig)
    out["drop_relations"] = sorted(out["drop_relations"])
    return out


def assert_teacher_cache_matches(cache_dir):
    stamp_path = os.path.join(cache_dir, "_ABLATION_STAMP.json")
    sig = teacher_cache_signature()

    if os.path.exists(stamp_path):
        with open(stamp_path) as f:
            old = json.load(f)
        if _normalise_signature(old) != _normalise_signature(sig):
            raise SystemExit(
                f"Teacher cache {cache_dir} was built with {old} but this run needs {sig}.\n"
                f"Use a fresh --teacher_cache_dir for this arm; reusing it would train "
                f"against the wrong teacher labels."
            )
        if old != sig:  # same meaning, older key set -- upgrade in place
            with open(stamp_path, "w") as f:
                json.dump(sig, f, indent=2)
        return

    production = _normalise_signature({"sd_edge_weight": os.environ.get("SD_EDGE_WEIGHT", "0.9")})
    existing = [p for p in os.listdir(cache_dir) if p.endswith(".pt")] if os.path.isdir(cache_dir) else []
    if existing and _normalise_signature(sig) != production:
        raise SystemExit(
            f"Teacher cache {cache_dir} already holds {len(existing)} unstamped entries, but this "
            f"run ablates the teacher ({sig}). Point --teacher_cache_dir at a fresh directory."
        )
    os.makedirs(cache_dir, exist_ok=True)
    with open(stamp_path, "w") as f:
        json.dump(sig, f, indent=2)


def ablated_loss_terms():
    names = _env_list("ABLATE_LOSS")
    bad = [n for n in names if n not in LOSS_TERMS]
    if bad:
        raise ValueError(f"ABLATE_LOSS contains unknown term(s) {bad}; expected from {sorted(LOSS_TERMS)}")
    return names


def apply_loss_flags(config):
    off = set(ablated_loss_terms())
    for term, key in LOSS_TERMS.items():
        config[key] = term not in off
    config["ablated_loss_terms"] = sorted(off)
    return config


def describe():
    return (
        f"DROP_RELATIONS={dropped_relations() or 'none'}  "
        f"ABLATE_LOSS={ablated_loss_terms() or 'none'}  "
        f"TAINT_ONLY_TEACHER={os.environ.get('TAINT_ONLY_TEACHER', '0')}"
    )

