# oracle_analysis_module.py
from slither_sdg_core import is_arithmetic, norm_var, ir_reads, ir_write, reads_block_info

# ---------------- Oracle / TWAP / Sensitive state ----------------
ORACLE_CALLS = {"latestRoundData", "latestAnswer", "getReserves", "observe", "slot0", "getPrice", "consult"}
TWAP_CALLS = {"observe", "price0CumulativeLast", "price1CumulativeLast"}
SENSITIVE_STATE = {"collateral", "balance", "liquidationThreshold", "price"}

# ---------------- IR helpers ----------------
def is_oracle_call(ir):
    callee = (
        getattr(ir, "function_name", None)
        or getattr(ir, "name", None)
        or getattr(getattr(ir, "function", None), "name", None)
    )
    if callee in ORACLE_CALLS:
        return True, "twap" if callee in TWAP_CALLS else "generic"
    return False, None

# ---------------- Node-level feature extraction ----------------

taint_map = {}

def oracle_node_callback(ir, cfg_node, function, contract, node_id, **kwargs):
    """
    Extract a rich set of oracle-related features for SC02 vulnerability analysis.
    taint_map: dict keeping track of variables tainted by oracle inputs
    """
    label = str(ir)
    reads = ir_reads(ir)
    write = ir_write(ir)
    state_vars = kwargs["state_vars"]

    # Oracle detection
    is_oracle, oracle_kind = is_oracle_call(ir)

    # Track taint propagation
    tainted = False
    num_deps = 0
    for v in reads:
        base = norm_var(v)
        if base in taint_map and taint_map[base]:
            tainted = True
            num_deps += 1

    # Update taint map for writes
    if write:
        base = norm_var(write)
        taint_map[base] = is_oracle or tainted

    features = {
        "is_oracle_call": is_oracle,
        "tainted_by_oracle": tainted or is_oracle,
        "writes_sensitive_state": write in SENSITIVE_STATE if write else False,
        "is_before_state_update": write not in SENSITIVE_STATE if write else True,
        "is_transfer": "transfer" in label.lower(),
        "is_liquidation": "liquidate" in label.lower(),
        # "is_conditional_on_oracle": False,  # could be inferred from CF edges later
        # "branch_involves_oracle": False,  # could be inferred from CF edges
        "has_limit_checks": any(k in label.lower() for k in ("<", ">", "<=", ">=")),
        "reads_block_info": reads_block_info(ir),
        "is_state_write": write in state_vars,
        "is_twap": oracle_kind == "twap",
    }

    semantic = {
        "oracle_kind": oracle_kind,
        "num_oracle_dependencies": num_deps,
        # "propagation_distance": 0,  # can be computed later in SDG
        "storage_slot": write if write in state_vars else None,
    }

    return features, semantic
