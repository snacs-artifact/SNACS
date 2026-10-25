pragma solidity ^0.4.15;
contract Parallax {
    mapping(uint => address) cup;
    address public constant referee = 0x6A0D0eBf1e532840baf224E1bD6A1d4489D5D78d;
    uint public deadline = 2000 finney;
    uint public highestBid = 0;
    uint public lowestBid = deadline*2;
    function() payable {
        require(msg.value % 2 finney == 0);
        if(msg.value > highestBid)
            require(this.balance - msg.value < deadline);
        if(msg.value < lowestBid)   lowestBid = msg.value;
        if(msg.value > highestBid)  highestBid = msg.value;
        cup[msg.value] = msg.sender;
        if(this.balance >= deadline) {
            uint finderAmount = (highestBid + lowestBid)/2;
            address finderAddress = cup[finderAmount];
            if (finderAddress == 0x0)
                finderAddress = cup[highestBid];
            highestBid = 0;
            lowestBid = deadline*2;
            finderAddress.transfer(this.balance - 100 finney);
            referee.transfer(100 finney);
        } 
    }
}