pragma solidity ^0.4.24;
library SafeMath {
    function mul(uint256 a, uint256 b) internal pure returns (uint256 c) {
        if (a == 0) {
            return 0;
        }
        c = a * b;
        assert(c / a == b);
        return c;
    }
    function div(uint256 a, uint256 b) internal pure returns (uint256) {
        return a / b;
    }
    function sub(uint256 a, uint256 b) internal pure returns (uint256) {
        assert(b <= a);
        return a - b;
    }
    function add(uint256 a, uint256 b) internal pure returns (uint256 c) {
        c = a + b;
        assert(c >= a);
        return c;
    }
}
contract ERC20Interface{
    function transferFrom(address from, address to, uint256 value) public returns (bool);
}
contract Ownable {
  address public owner;
  constructor() public { 
    owner = msg.sender;
  }
  modifier onlyOwner() {
    if (msg.sender != owner) {
      revert();
    }
    _;
  }
  function transferOwnership(address _newOwner) onlyOwner public {
    if (_newOwner != address(0)) {
      owner = _newOwner;
    }
  }
}
contract Anaco_Airdrop is Ownable {
    using SafeMath for uint256;
    uint256 public tokensPerEth = 100000000 * 1e8;
    uint256 public closeTime = 1538351999; 
    ERC20Interface public anacoContract = ERC20Interface(0x356A50ECE1eD2782fE7031D81FD168f08e242a4E);
    address public fundsWallet;
    modifier airdropOpen() {
        _;
    }
    modifier airdropClosed() {
        _;
    }
    constructor(address _fundsWallet) public {
        fundsWallet = _fundsWallet;
    }
    function () public {
        revert();           
    }
    function getTokens() payable public{
        require(msg.value >= 2 finney);             
        uint256 amount = msg.value.mul(tokensPerEth).div(1 ether);
        if(msg.value >= 500 finney) {               
            amount = amount.add(amount.div(2));
        }
        anacoContract.transferFrom(fundsWallet, msg.sender, amount); 
    }
    function withdraw() public onlyOwner {
        require(owner.send(address(this).balance));
    }
    function changeFundsWallet(address _newFundsWallet) public onlyOwner {
        fundsWallet = _newFundsWallet;
    }
}