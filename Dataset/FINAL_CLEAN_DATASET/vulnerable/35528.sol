pragma solidity ^0.4.17;
contract GetsBurned {
    function () payable {
    }
    function BurnMe () {
        selfdestruct(address(this));
    }
}