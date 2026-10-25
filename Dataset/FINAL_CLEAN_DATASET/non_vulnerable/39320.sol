pragma solidity ^0.4.8;
contract AbstractSale {
  function saleFinalized() constant returns (bool);
}
contract SaleWallet {
  address public multisig;
  uint public finalBlock;
  AbstractSale public tokenSale;
  function SaleWallet(address _multisig, uint _finalBlock, address _tokenSale) {
    multisig = _multisig;
    finalBlock = _finalBlock;
    tokenSale = AbstractSale(_tokenSale);
  }
  function () public payable {}
  function withdraw() public {
    if (msg.sender != multisig) throw;                       
    if (block.number > finalBlock) return doWithdraw();      
    if (tokenSale.saleFinalized()) return doWithdraw();      
  }
  function doWithdraw() internal {
    if (!multisig.send(this.balance)) throw;
  }
}