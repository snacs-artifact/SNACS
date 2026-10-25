# auth_postpass.py
# Authorization post-pass, applied to every SDG after it is built.
# A require/assert/modifier check whose condition uses msg.sender gets guard_kind "auth"; 
#tx.origin gives "auth_weak". 
from collections import defaultdict

SENDER_TOKENS = ("msg.sender", "_msgsender", "msgsender()")
WEAK_TOKENS = ("tx.origin",)
AUTH_GUARD_CALLS = ("onlyowner", "hasrole", "_checkrole", "onlyrole",
                    "onlyadmin", "requireowner", "onlygovernance")
# a guard must be a CHECK, not merely a statement mentioning the sender
CHECK_MARKERS = ("solidity_call require", "solidity_call assert", "modifier_call")


def _lab(n):
    return (n.get("label") or "").lower()


def apply(graph):
    nodes = {n["id"]: n for n in graph["nodes"]}
    dd_in = defaultdict(list)
    for e in graph["edges"]:
        if e["type"] in ("dd", "seq"):
            dd_in[e["to"]].append(e["from"])

    stats = {"auth": 0, "auth_weak": 0, "sender_cond": 0, "modifier_auth": 0}

    for nid, node in nodes.items():
        feats = node.setdefault("features", {})
        sem = node.setdefault("semantic", {})
        lab = _lab(node)

        is_check = bool(feats.get("is_require") or feats.get("is_assert")) or \
            any(m in lab for m in CHECK_MARKERS)
        if not is_check:
            continue

        # (A) modifier call to a known authorization modifier -- direct evidence
        if "modifier_call" in lab and any(k in lab for k in AUTH_GUARD_CALLS):
            sem["guard_kind"] = "auth"
            feats["condition_involves_sender"] = True
            stats["auth"] += 1
            stats["modifier_auth"] += 1
            continue

        # (B) the checked condition, recovered one hop back along dd/seq
        strong = any(t in lab for t in SENDER_TOKENS) or \
            any(k in lab for k in AUTH_GUARD_CALLS)
        weak = any(t in lab for t in WEAK_TOKENS)
        if not strong:
            for src_id in dd_in.get(nid, []):
                src = nodes.get(src_id)
                if src is None:
                    continue
                sl = _lab(src)
                if any(t in sl for t in SENDER_TOKENS):
                    strong = True
                    break
                if any(t in sl for t in WEAK_TOKENS):
                    weak = True

        if strong:
            sem["guard_kind"] = "auth"
            feats["condition_involves_sender"] = True
            stats["auth"] += 1
            stats["sender_cond"] += 1
        elif weak:
            # tx.origin is NOT sound authorization; kept distinct on purpose
            sem["guard_kind"] = "auth_weak"
            feats["condition_involves_sender"] = True
            stats["auth_weak"] += 1
    return stats
