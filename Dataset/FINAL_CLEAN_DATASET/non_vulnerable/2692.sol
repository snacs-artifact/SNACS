pragma solidity ^0.4.23;
contract ERC721 {
  event Transfer(
    address indexed from,
    address indexed to,
    uint256 indexed tokenId
  );
  event Approval(
    address indexed owner,
    address indexed approved,
    uint256 indexed tokenId
  );
  function implementsERC721() public pure returns (bool);
  function totalSupply() public view returns (uint256 total);
  function balanceOf(address _owner) public view returns (uint256 balance);
  function ownerOf(uint256 _tokenId) external view returns (address owner);
  function approve(address _to, uint256 _tokenId) external;
  function transfer(address _to, uint256 _tokenId) external;
  function transferFrom(address _from, address _to, uint256 _tokenId) external;
}
contract Ownable {
  address public owner;
  event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
  constructor() public {
    owner = msg.sender;
  }
  modifier onlyOwner() {
    require(msg.sender == owner);
    _;
  }
  function transferOwnership(address newOwner) public onlyOwner {
    require(newOwner != address(0));
    emit OwnershipTransferred(owner, newOwner);
    owner = newOwner;
  }
}
contract Pausable is Ownable {
  event Pause();
  event Unpause();
  bool public paused = false;
  modifier whenNotPaused() {
    require(!paused);
    _;
  }
  modifier whenPaused() {
    require(paused);
    _;
  }
  function pause() onlyOwner whenNotPaused public {
    paused = true;
    emit Pause();
  }
  function unpause() onlyOwner whenPaused public {
    paused = false;
    emit Unpause();
  }
}
contract CurioAuction is Pausable {
  event AuctionCreated(
    uint256 indexed tokenId,
    uint256 startingPrice,
    uint256 endingPrice,
    uint256 duration
  );
  event AuctionSuccessful(
    uint256 indexed tokenId,
    uint256 totalPrice,
    address indexed winner
  );
  event AuctionCancelled(uint256 indexed tokenId);
  struct Auction {
    address seller;
    uint128 startingPrice;
    uint128 endingPrice;
    uint64 duration;
    uint64 startedAt;
  }
  bool public isCurioAuction = true;
  ERC721 public tokenContract;
  uint256 public feePercent;
  mapping (uint256 => Auction) tokenIdToAuction;
  uint256 public releaseTokensSaleCount;
  uint256 public auctionPriceLimit;
  constructor(
    address _tokenAddress,
    uint256 _fee,
    uint256 _auctionPriceLimit
  )
    public
  {
    require(_fee <= 10000);
    feePercent = _fee;
    ERC721 candidateContract = ERC721(_tokenAddress);
    require(candidateContract.implementsERC721());
    tokenContract = candidateContract;
    require(_auctionPriceLimit == uint256(uint128(_auctionPriceLimit)));
    auctionPriceLimit = _auctionPriceLimit;
  }
  function createAuction(
    uint256 _tokenId,
    uint256 _startingPrice,
    uint256 _endingPrice,
    uint256 _duration,
    address _seller
  )
    whenNotPaused
    external
  {
    require(_startingPrice == uint256(uint128(_startingPrice)));
    require(_startingPrice < auctionPriceLimit);
    require(_endingPrice == uint256(uint128(_endingPrice)));
    require(_endingPrice < auctionPriceLimit);
    require(_duration == uint256(uint64(_duration)));
    require(msg.sender == address(tokenContract));
    _deposit(_seller, _tokenId);
    Auction memory auction = Auction(
      _seller,
      uint128(_startingPrice),
      uint128(_endingPrice),
      uint64(_duration),
      uint64(now)
    );
    _addAuction(_tokenId, auction);
  }
  function getAuction(uint256 _tokenId) external view
  returns
  (
    address seller,
    uint256 startingPrice,
    uint256 endingPrice,
    uint256 duration,
    uint256 startedAt
  ) {
    Auction storage auction = tokenIdToAuction[_tokenId];
    require(_isOnAuction(auction));
    return (
      auction.seller,
      auction.startingPrice,
      auction.endingPrice,
      auction.duration,
      auction.startedAt
    );
  }
  function getCurrentPrice(uint256 _tokenId) external view returns (uint256) {
    Auction storage auction = tokenIdToAuction[_tokenId];
    require(_isOnAuction(auction));
    return _currentPrice(auction);
  }
  function bid(uint256 _tokenId) external payable whenNotPaused {
    address seller = tokenIdToAuction[_tokenId].seller;
    _bid(_tokenId, msg.value);
    _transfer(msg.sender, _tokenId);
    if (seller == address(tokenContract)) {
      releaseTokensSaleCount++;
    }
  }
  function cancelAuction(uint256 _tokenId) external {
    Auction storage auction = tokenIdToAuction[_tokenId];
    require(_isOnAuction(auction));
    address seller = auction.seller;
    require(msg.sender == seller);
    _cancelAuction(_tokenId, seller);
  }
  function cancelAuctionWhenPaused(uint256 _tokenId) whenPaused onlyOwner external {
    Auction storage auction = tokenIdToAuction[_tokenId];
    require(_isOnAuction(auction));
    _cancelAuction(_tokenId, auction.seller);
  }
  function withdrawBalance() external {
    address tokenAddress = address(tokenContract);
    require(msg.sender == owner || msg.sender == tokenAddress);
    bool res = tokenAddress.send(address(this).balance);
  }
  function setAuctionPriceLimit(uint256 _newAuctionPriceLimit) external {
    address tokenAddress = address(tokenContract);
    require(msg.sender == owner || msg.sender == tokenAddress);
    require(_newAuctionPriceLimit == uint256(uint128(_newAuctionPriceLimit)));
    auctionPriceLimit = _newAuctionPriceLimit;
  }
  function _owns(
    address _claimant,
    uint256 _tokenId
  )
    internal
    view
    returns (bool)
  {
    return (tokenContract.ownerOf(_tokenId) == _claimant);
  }
  function _deposit(
    address _owner,
    uint256 _tokenId
  )
    internal
  {
    tokenContract.transferFrom(_owner, this, _tokenId);
  }
  function _transfer(
    address _receiver,
    uint256 _tokenId
  )
    internal
  {
    tokenContract.transfer(_receiver, _tokenId);
  }
  function _addAuction(
    uint256 _tokenId,
    Auction _auction
  )
    internal
  {
    require(_auction.duration >= 1 minutes);
    tokenIdToAuction[_tokenId] = _auction;
    emit AuctionCreated(
      uint256(_tokenId),
      uint256(_auction.startingPrice),
      uint256(_auction.endingPrice),
      uint256(_auction.duration)
    );
  }
  function _removeAuction(uint256 _tokenId) internal {
    delete tokenIdToAuction[_tokenId];
  }
  function _cancelAuction(
    uint256 _tokenId,
    address _seller
  )
    internal
  {
    _removeAuction(_tokenId);
    _transfer(_seller, _tokenId);
    emit AuctionCancelled(_tokenId);
  }
  function _isOnAuction(Auction storage _auction) internal view returns (bool) {
    return (_auction.startedAt > 0);
  }
  function _calculateFee(uint256 _price) internal view returns (uint256) {
    return _price * feePercent / 10000;
  }
  function _currentPrice(Auction storage _auction) internal view returns (uint256) {
    uint256 secondsPassed = 0;
    if (now > _auction.startedAt) {
      secondsPassed = now - _auction.startedAt;
    }
    return _calculateCurrentPrice(
      _auction.startingPrice,
      _auction.endingPrice,
      _auction.duration,
      secondsPassed
    );
  }
  function _calculateCurrentPrice(
    uint256 _startingPrice,
    uint256 _endingPrice,
    uint256 _duration,
    uint256 _secondsPassed
  )
    internal
    pure
    returns (uint256)
  {
    if (_secondsPassed >= _duration) {
      return _endingPrice;
    } else {
      int256 totalPriceChange = int256(_endingPrice) - int256(_startingPrice);
      int256 currentPriceChange = totalPriceChange * int256(_secondsPassed) / int256(_duration);
      int256 currentPrice = int256(_startingPrice) + currentPriceChange;
      return uint256(currentPrice);
    }
  }
  function _bid(
    uint256 _tokenId,
    uint256 _bidAmount
  )
    internal
    returns (uint256)
  {
    Auction storage auction = tokenIdToAuction[_tokenId];
    require(_isOnAuction(auction));
    uint256 price = _currentPrice(auction);
    require(_bidAmount >= price);
    address seller = auction.seller;
    _removeAuction(_tokenId);
    if (price > 0) {
      uint256 fee = _calculateFee(price);
      uint256 sellerProceeds = price - fee;
      seller.transfer(sellerProceeds);
    }
    uint256 bidExcess = _bidAmount - price;
    msg.sender.transfer(bidExcess);
    emit AuctionSuccessful(_tokenId, price, msg.sender);
    return price;
  }
}