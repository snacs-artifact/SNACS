pragma solidity ^0.4.0;
contract GetsBurned {
    function () payable public {
    }
    function BurnMe() public {
        selfdestruct(address(this));
    }
}