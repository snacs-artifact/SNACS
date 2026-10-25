# flashloan_analysis_module.py
from slither.core.cfg.node import NodeType

# --- Constants for detection ---
FINANCIAL_FUNCS = {
    "balanceOf",
    "transfer",
    "transferFrom",
    "approve",
    "getReserves",
    "swapExactTokensForTokens",
    "flashLoan",
    "executeOperation",
    "swap",
    "borrow",
    "repay",
    "totalSupply",
}

REENTRANCY_GUARDS = {"nonReentrant", "_lock"}

LENDING_POOLS = {"AaveLendingPool", "CompoundLendingPool", "DyDxPool"}

def flashloan_node_callback(ir, cfg_node, function, contract, node_id, **kwargs):
    """
    Extract per-node features relevant for detecting flash loan attacks
    """
    label = str(ir)

    # Reads and writes
    reads = getattr(ir, "read", [])
    if callable(reads):
        reads = reads()
    writes = getattr(ir, "write", [])
    if callable(writes):
        writes = writes()

    # Detect callee / receiver
    callee_name = (
        getattr(ir, "function_name", None)
        or getattr(ir, "name", None)
        or getattr(getattr(ir, "function", None), "name", None)
    )

    # --- Node-level features ---
    features = {
        # Control flow
        "is_loop": getattr(cfg_node, "type", None) in {NodeType.STARTLOOP, NodeType.IFLOOP} if not isinstance(getattr(cfg_node, "type", None), list) else False,
        "is_assert": "assert" in label,
        # Financial operations
        "large_arithmetic_operation": "*" in label or "/" in label,
        "calls_financial_function": callee_name in FINANCIAL_FUNCS,
        # External interaction
        "value_forwarded": "msg.value" in label,
        # Reentrancy and guards
        "reentrancy_guard_present": any(g in label for g in REENTRANCY_GUARDS),
    }

    # --- Semantic info ---
    semantic = {
        "guard_kind": (
            "reentrancy_guard"
            if any(g in label for g in REENTRANCY_GUARDS)
            else None
        ),
    }

    return features, semantic
