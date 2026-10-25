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
contract IERC20Token {
    function name() public constant returns (string) {}
    function symbol() public constant returns (string) {}
    function decimals() public constant returns (uint8) {}
    function totalSupply() public constant returns (uint256) {}
    function balanceOf(address _owner) public constant returns (uint256) { _owner; }
    function allowance(address _owner, address _spender) public constant returns (uint256) { _owner; _spender; }
    function transfer(address _to, uint256 _value) public returns (bool success);
    function transferFrom(address _from, address _to, uint256 _value) public returns (bool success);
    function approve(address _spender, uint256 _value) public returns (bool success);
}
contract ITokenHolder is Ownable {
    function withdrawTokens(IERC20Token _token, address _to, uint256 _amount) public;
}
contract TokenHolder is ITokenHolder {
    function TokenHolder() {
    }
    function withdrawTokens(IERC20Token _token, address _to, uint256 _amount)
    public
    onlyOwner
    {
        require(_token != address(0x0));
        require(_to != address(0x0));
        require(_to != address(this));
        assert(_token.transfer(_to, _amount));
    }
}
contract CrowdFunding is Claimable, TokenHolder {
    using SafeMath for uint256;
    address public walletBeneficiary;
    uint256 public weiRaised;
    bool public isFinalized = false;
    modifier isNotFinalized() {
        require(!isFinalized);
        _;
    }
    event DonateAdded(address indexed _from, address indexed _to,uint256 _amount);
    event DonationMatched(address indexed _from, address indexed _to,uint256 _amount);
    event Finalized();
    event ClaimBalance(address indexed _grantee, uint256 _amount);
    function CrowdFunding(address _walletBeneficiary) public {
        require(_walletBeneficiary != address(0));
        walletBeneficiary = _walletBeneficiary;
    }
    function deposit() onlyOwner isNotFinalized external payable {
    }
    function() isNotFinalized external payable {
        donate();
    }
    function donate() isNotFinalized public payable {
        require(msg.value > 0);
        uint256 weiAmount = msg.value;
        weiRaised = weiRaised.add(weiAmount);
        walletBeneficiary.transfer(weiAmount);
        DonateAdded(msg.sender, walletBeneficiary, weiAmount);
        if(this.balance >= weiAmount) {
            weiRaised = weiRaised.add(weiAmount);
            walletBeneficiary.transfer(weiAmount);
            DonationMatched(address(this), walletBeneficiary, weiAmount);
        } else {
            weiRaised = weiRaised.add(this.balance);
            walletBeneficiary.transfer(this.balance);
            DonationMatched(address(this), walletBeneficiary, this.balance);
        }
    }
    function finalizeDonation(address beneficiary) onlyOwner isNotFinalized public {
        require(beneficiary != address(0));
        uint256 weiAmount = this.balance;
        beneficiary.transfer(weiAmount);
        ClaimBalance(beneficiary, weiAmount);
        isFinalized = true;
        Finalized();
    }
}