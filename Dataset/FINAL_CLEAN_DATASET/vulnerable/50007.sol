pragma solidity ^0.4.24;
contract ForceEther {
  constructor() public payable { }
  function destroyAndSend(address _recipient) public {
    selfdestruct(_recipient);
  }
}