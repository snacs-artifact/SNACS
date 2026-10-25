pragma solidity ^0.4.10;
contract VoteFactory {
    address public owner;
    uint public numPolls;
    uint public nextEndTime;
    Vote public yesContract;
    Vote public noContract;
    mapping(uint => string) public voteDescription;
    mapping(address => mapping(uint => bool)) public hasVoted;
    mapping(uint => uint) public numVoters; 
    mapping(uint => mapping(uint => address)) public voter; 
    mapping(uint => uint) public yesCount; 
    mapping(uint => uint) public noCount;
    event transferredOwner(address newOwner);
    event startedNewVote(address initiator, uint duration, string description, uint voteId);
    event voted(address voter, bool isYes);
    modifier onlyOwner {
        if (msg.sender != owner)
            throw;
        _;
    }
    function transferOwner(address newOwner) onlyOwner {
        owner = newOwner;
        transferredOwner(newOwner);
    }
    function payOut() onlyOwner {
        owner.send(this.balance);
    }
    function VoteFactory() {
        owner = msg.sender;
        yesContract = new Vote();
        noContract = new Vote();
    }
    function() payable {
        if (nextEndTime < now + 10 minutes)
            startNewVote(10 minutes, "Vote on tax reimbursements");
    }
    function newVote(uint duration, string description) onlyOwner {
        startNewVote(duration, description);
    }
    function startNewVote(uint duration, string description) internal {
        if (now <= nextEndTime)
            throw;
        nextEndTime = now + duration;
        voteDescription[numPolls] = description;
        startedNewVote(msg.sender, duration, description, ++numPolls);
    }
    function vote(bool isYes, address voteSender) {
        if (msg.sender != address(yesContract) && msg.sender != address(noContract))
            throw;
        if (now > nextEndTime)
            throw;
        if (hasVoted[voteSender][numPolls])
            throw;
        hasVoted[voteSender][numPolls] = true;
        voter[numPolls][numVoters[numPolls]++] = voteSender;
        if (isYes)
            yesCount[numPolls]++;
        else
            noCount[numPolls]++;
        voted(voteSender, isYes);
    }
}
contract Vote {
    VoteFactory public myVoteFactory;
    function Vote() {
        myVoteFactory = VoteFactory(msg.sender);
    }
    function () payable {
        myVoteFactory.vote(this == myVoteFactory.yesContract(), msg.sender);
    }
    function payOut() {
        msg.sender.send(this.balance);
    }
}