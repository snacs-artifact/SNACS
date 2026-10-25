import sys
from slither_sdg_core import slither_analyze
from access_control_analysis_module import acl_node_callback

# from reentrancy_analysis import re_node_callback, re_edge_callback  # future modules
from oracle_analysis_module import oracle_node_callback
from flashloan_analysis_module import flashloan_node_callback

if __name__ == "__main__":
    if len(sys.argv) not in [2, 3]:
        print("Usage: python slither_sdg_generator.py <contract.sol> [solidity_version]")
        sys.exit(1)

    contract_path = sys.argv[1]
    solidity_version = None
    if len(sys.argv) == 3:
        solidity_version = sys.argv[2]

    modules = [
        acl_node_callback,
        # Add future modules here, all merged into the same graph
        # re_node_callback,
        oracle_node_callback,
        flashloan_node_callback,
    ]

    slither_analyze(contract_path, modules, solidity_version)
