pragma solidity ^0.4.18;
library SafeMath {
  function mul(uint256 a, uint256 b) internal pure returns (uint256) {
    uint256 c = a * b;
    assert(a == 0 || c / a == b);
    return c;
  }
  function div(uint256 a, uint256 b) internal pure returns (uint256) {
    uint256 c = a / b;
    return c;
  }
  function sub(uint256 a, uint256 b) internal pure returns (uint256) {
    assert(b <= a);
    return a - b;
  }
  function add(uint256 a, uint256 b) internal pure returns (uint256) {
    uint256 c = a + b;
    assert(c >= a);
    return c;
  }
}
contract Ownable {
  address public owner;
  event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
  function Ownable() public {
    owner = msg.sender;
  }
  modifier onlyOwner() {
    require(msg.sender == owner);
    _;
  }
  function transferOwnership(address newOwner) public onlyOwner {
    require(newOwner != address(0));
    OwnershipTransferred(owner, newOwner);
    owner = newOwner;
  }
}
contract Claimable is Ownable {
    address public pendingOwner;
    modifier onlyPendingOwner() {
        require(msg.sender == pendingOwner);
        _;
    }
    function transferOwnership(address newOwner) onlyOwner public {
        pendingOwner = newOwner;
    }
    function claimOwnership() onlyPendingOwner public {
        OwnershipTransferred(owner, pendingOwner);
        owner = pendingOwner;
        pendingOwner = address(0);
    }
}
contract CrowdFunding is Claimable {
    using SafeMath for uint256;
    address public walletBeneficiary;
    uint256 public weiRaised;
    bool public isFinalized = false;
    modifier isNotFinalized() {
        require(!isFinalized);
        _;
    }
    event DonateAdded(address indexed _from, address indexed _to,uint256 _amount);
    event Finalized();
    event ClaimBalance(address indexed _grantee, uint256 _amount);
    function CrowdFunding(address _walletBeneficiary) public {
        require(_walletBeneficiary != address(0));
        walletBeneficiary = _walletBeneficiary;
    }
    function deposit() onlyOwner isNotFinalized external payable {
    }
    function() external payable {
        donate();
    }
    function donate() public payable {
        require(!isFinalized);
        uint256 weiAmount = msg.value;
        weiRaised = weiRaised.add(weiAmount);
        walletBeneficiary.transfer(weiAmount);
        DonateAdded(msg.sender, walletBeneficiary, weiAmount);
        if(this.balance >= weiAmount) {
            weiRaised = weiRaised.add(weiAmount);
            walletBeneficiary.transfer(weiAmount);
            DonateAdded(address(this), walletBeneficiary, weiAmount);
        } else {
            weiRaised = weiRaised.add(this.balance);
            walletBeneficiary.transfer(this.balance);
            DonateAdded(address(this), walletBeneficiary, this.balance);
        }
    }
    function claimBalanceByOwner(address beneficiary) onlyOwner isNotFinalized public {
        require(beneficiary != address(0));
        uint256 weiAmount = this.balance;
        beneficiary.transfer(weiAmount);
        ClaimBalance(beneficiary, weiAmount);
    }
    function finalizeDonation(address beneficiary) onlyOwner isNotFinalized public {
        require(beneficiary != address(0));
        claimBalanceByOwner(beneficiary);
        isFinalized = true;
        Finalized();
    }
}