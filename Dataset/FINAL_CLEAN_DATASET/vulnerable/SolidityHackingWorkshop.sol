pragma solidity ^0.4.10;
contract SimpleToken{
    mapping(address => uint) public balances;
    function buyToken() payable {
        balances[msg.sender]+=msg.value / 1 ether;
    }
    function sendToken(address _recipient, uint _amount) {
        require(balances[msg.sender]!=0); 
        balances[msg.sender]-=_amount;
        balances[_recipient]+=_amount;
    }
}
contract VoteTwoChoices{
    mapping(address => uint) public votingRights;
    mapping(address => uint) public votesCast;
    mapping(bytes32 => uint) public votesReceived;
    function buyVotingRights() payable {
        votingRights[msg.sender]+=msg.value/(1 ether);
    }
    function vote(uint _nbVotes, bytes32 _proposition) {
        require(_nbVotes + votesCast[msg.sender]<=votingRights[msg.sender]); 
        votesCast[msg.sender]+=_nbVotes;
        votesReceived[_proposition]+=_nbVotes;
    }
}
contract BuyToken {
    mapping(address => uint) public balances;
    uint public price=1;
    address public owner=msg.sender;
    function buyToken(uint _amount, uint _price) payable {
        require(_price>=price); 
        require(_price * _amount * 1 ether <= msg.value); 
        balances[msg.sender]+=_amount;
    }
    function setPrice(uint _price) {
        require(msg.sender==owner);
        price=_price;
    }
}
contract Store {
    struct Safe {
        address owner;
        uint amount;
    }
    Safe[] public safes;
    function store() payable {
        safes.push(Safe({owner: msg.sender, amount: msg.value}));
    }
    function take() {
        for (uint i; i<safes.length; ++i) {
            Safe safe = safes[i];
            if (safe.owner==msg.sender && safe.amount!=0) {
                msg.sender.transfer(safe.amount);
                safe.amount=0;
            }
        }
    }
}
contract CountContribution{
    mapping(address => uint) public contribution;
    uint public totalContributions;
    address owner=msg.sender;
    function CountContribution() public {
        recordContribution(owner, 1 ether);
    }
    function contribute() public payable {
        recordContribution(msg.sender, msg.value);
    }
    function recordContribution(address _user, uint _amount) {
        contribution[_user]+=_amount;
        totalContributions+=_amount;
    }
}
contract Token {
    mapping(address => uint) public balances;
    function buyToken() payable {
        balances[msg.sender]+=msg.value / 1 ether;
    }
    function sendToken(address _recipient, uint _amount) {
        require(balances[msg.sender]>=_amount); 
        balances[msg.sender]-=_amount;
        balances[_recipient]+=_amount;
    }
    function sendAllTokens(address _recipient) {
        balances[_recipient]=+balances[msg.sender];
        balances[msg.sender]=0;
    }
}
contract DiscountedBuy {
    uint public basePrice = 1 ether;
    mapping (address => uint) public objectBought;
    function buy() payable {
        require(msg.value * (1 + objectBought[msg.sender]) == basePrice);
        objectBought[msg.sender]+=1;
    }
    function price() constant returns(uint price) {
        return basePrice/(1 + objectBought[msg.sender]);
    }
}
contract HeadOrTail {
    bool public chosen; 
    bool lastChoiceHead; 
    address public lastParty; 
    function choose(bool _chooseHead) payable {
        require(!chosen);
        require(msg.value == 1 ether);
        chosen=true;
        lastChoiceHead=_chooseHead;
        lastParty=msg.sender;
    }
    function guess(bool _guessHead) payable {
        require(chosen);
        require(msg.value == 1 ether);
        if (_guessHead == lastChoiceHead)
            msg.sender.transfer(2 ether);
        else
            lastParty.transfer(2 ether);
        chosen=false;
    }
}
contract Vault {
    mapping(address => uint) public balances;
    function store() payable {
        balances[msg.sender]+=msg.value;
    }
    function redeem() {
        msg.sender.call.value(balances[msg.sender])();
        balances[msg.sender]=0;
    }
}
contract HeadTail {
    address public partyA;
    address public partyB;
    bytes32 public commitmentA;
    bool public chooseHeadB;
    uint public timeB;
    function HeadTail(bytes32 _commitmentA) payable {
        require(msg.value == 1 ether);
        commitmentA=_commitmentA;
        partyA=msg.sender;
    }
    function guess(bool _chooseHead) payable {
        require(msg.value == 1 ether);
        require(partyB==address(0));
        chooseHeadB=_chooseHead;
        timeB=now;
        partyB=msg.sender;
    }
    function resolve(bool _chooseHead, uint _randomNumber) {
        require(msg.sender == partyA);
        require(keccak256(_chooseHead, _randomNumber) == commitmentA);
        require(this.balance >= 2 ether);
        if (_chooseHead == chooseHeadB)
            partyB.transfer(2 ether);
        else
            partyA.transfer(2 ether);
    }
    function timeOut() {
        require(now > timeB + 1 days);
        require(this.balance>=2 ether);
        partyB.transfer(2 ether);
    }
}
contract Coffers {
    struct Coffer {address owner; uint[] slots;}
    Coffer[] public coffers;
    function createCoffer(uint _slots) external {
        Coffer storage coffer = coffers[coffers.length++];
        coffer.owner = msg.sender;
        coffer.slots.length = _slots;
    }
    function deposit(uint _coffer, uint _slot) payable external {
        Coffer storage coffer = coffers[_coffer];
        coffer.slots[_slot] += msg.value;
    }
    function withdraw(uint _coffer, uint _slot) external {
        Coffer storage coffer = coffers[_coffer];
        require(coffer.owner == msg.sender);
        msg.sender.transfer(coffer.slots[_slot]);
        coffer.slots[_slot] = 0;
    }
}