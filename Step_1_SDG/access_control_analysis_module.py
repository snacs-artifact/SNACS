# access_control_analysis_module.py
from slither.core.cfg.node import NodeType
from slither_sdg_core import (
    ir_reads_tx_origin,
    is_arithmetic,
    is_call_ir,
    is_delegatecall,
    is_external_call,
    is_require,
    ir_reads,
    ir_write,
)

PRIV_SLOTS = {"owner", "admin", "admins", "roles", "authorized"}
TWAP_CALLS = {"observe", "price0CumulativeLast", "price1CumulativeLast"}
AUTH_GUARD_CALLS = {"onlyOwner", "hasRole", "_checkRole", "onlyRole", "onlyAdmin"}


def acl_node_callback(ir, cfg_node, function, contract, node_id, **kwargs):
    label = str(ir)
    reads = ir_reads(ir)
    write = ir_write(ir)
    is_entry, is_upgradeable = kwargs["is_entry"], kwargs["is_upgradeable"]

    callee = (
        getattr(ir, "function_name", None)
        or getattr(ir, "name", None)
        or getattr(getattr(ir, "function", None), "name", None)
    )
    if callee is not None:
        callee = str(callee)
    receiver = getattr(ir, "destination", None) or getattr(ir, "called", None)
    if receiver is not None:
        receiver = receiver.name

    features = {
        "is_conditional": getattr(cfg_node, "type", None) in {NodeType.IF, NodeType.IFLOOP} if not isinstance(getattr(cfg_node, "type", None), list) else False,
        "is_require": is_require(ir),
        "uses_msg_sender": "msg.sender" in label,
        "uses_tx_origin": "tx.origin" in label,
        "condition_involves_sender": False,
        "condition_involves_role_mapping": any(k in label.lower() for k in ("hasrole", "_checkrole", "roles[")),
        "reads_privileged_state": any(v in PRIV_SLOTS for v in reads),
        "writes_privileged_state": write in PRIV_SLOTS if write else False,
        "is_external_call": is_external_call(ir),
        "is_delegatecall": is_delegatecall(ir),
        "call_target_user_controlled": False,
        "is_before_state_update": False,
        "is_before_external_call": False,
        "in_modifier": bool(getattr(function, "_modifiers", None)) or "modifier_call" in label.lower(),
        "function_is_entry_point": is_entry,
        "contract_is_upgradeable": is_upgradeable,
        "has_time": "block.timestamp" in label,
        "is_arithmetic": is_arithmetic(ir),
    }

    semantic = {
        "guard_kind": (
            "auth"
            if any(k in label for k in AUTH_GUARD_CALLS) or "msg.sender" in label
            else "auth_weak" if ir_reads_tx_origin(ir) else None
        ),
        "callee": callee,
        "receiver": receiver,
    }

    return features, semantic
