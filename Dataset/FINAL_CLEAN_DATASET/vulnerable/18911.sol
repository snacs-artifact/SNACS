pragma solidity ^0.4.18;
contract ERC223 {
    function totalSupply() constant public returns (uint256 outTotalSupply);
    function balanceOf( address _owner) constant public returns (uint256 balance);
    function transfer( address _to, uint256 _value) public returns (bool success);
    function transfer( address _to, uint256 _value, bytes _data) public returns (bool success);
    function transferFrom( address _from, address _to, uint256 _value) public returns (bool success);
    function approve( address _spender, uint256 _value) public returns (bool success);
    function allowance( address _owner, address _spender) constant public returns (uint256 remaining);
    event Transfer( address indexed _from, address indexed _to, uint _value, bytes _data);
    event Approval( address indexed _owner, address indexed _spender, uint256 _value);
}
contract ERC223Receiver { 
    function tokenFallback(address _from, uint _value, bytes _data) public;
}
contract OwnerBase {
    address public ceoAddress;
    address public cfoAddress;
    address public cooAddress;
    bool public paused = false;
    function OwnerBase() public {
       ceoAddress = msg.sender;
       cfoAddress = msg.sender;
       cooAddress = msg.sender;
    }
    modifier onlyCEO() {
        require(msg.sender == ceoAddress);
        _;
    }
    modifier onlyCFO() {
        require(msg.sender == cfoAddress);
        _;
    }
    modifier onlyCOO() {
        require(msg.sender == cooAddress);
        _;
    }
    function setCEO(address _newCEO) external onlyCEO {
        require(_newCEO != address(0));
        ceoAddress = _newCEO;
    }
    function setCFO(address _newCFO) external onlyCEO {
        require(_newCFO != address(0));
        cfoAddress = _newCFO;
    }
    function setCOO(address _newCOO) external onlyCEO {
        require(_newCOO != address(0));
        cooAddress = _newCOO;
    }
    modifier whenNotPaused() {
        require(!paused);
        _;
    }
    modifier whenPaused {
        require(paused);
        _;
    }
    function pause() external onlyCOO whenNotPaused {
        paused = true;
    }
    function unpause() public onlyCOO whenPaused {
        paused = false;
    }
}
contract RechargeMain is ERC223Receiver, OwnerBase {
	event EvtCoinSetted(address coinContract);
	event EvtRecharge(address customer, uint amount);
	ERC223 public coinContract;
    function RechargeMain(address coin) public {
        ceoAddress = msg.sender;
        cooAddress = msg.sender;
        cfoAddress = msg.sender;
		coinContract = ERC223(coin);
    }
    function setCoinInfo(address coin) public {
        require(msg.sender == ceoAddress || msg.sender == cooAddress);
		coinContract = ERC223(coin);
        emit EvtCoinSetted(coinContract);
    }
	function tokenFallback(address _from, uint _value, bytes ) public {
		require(msg.sender == address(coinContract));
		emit EvtRecharge(_from, _value);
	}
    function () public payable {
    }
    function withdrawTokens() external {
		address myself = address(this);
        uint256 fundNow = coinContract.balanceOf(myself);
        coinContract.transfer(cfoAddress, fundNow);
        uint256 balance = myself.balance;
        cfoAddress.transfer(balance);
    }
}