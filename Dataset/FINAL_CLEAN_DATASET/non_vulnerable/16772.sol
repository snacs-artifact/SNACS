pragma solidity ^0.4.11;
contract Ownable {
    address public owner;
    constructor () public {
        owner = msg.sender;
    }
    modifier onlyOwner() {
        require(msg.sender == owner);
        _;
    }
    function transferOwnership(address newOwner) onlyOwner public {
        if (newOwner != address(0)) {
            owner = newOwner;
        }
    }
}
contract ERC721 {
    function totalSupply() public view returns (uint256 total);
    function balanceOf(address _owner) public view returns (uint256 balance);
    function ownerOf(uint256 _tokenId) external view returns (address owner);
    function approve(address _to, uint256 _tokenId) external;
    function transfer(address _to, uint256 _tokenId) external;
    function transferFrom(address _from, address _to, uint256 _tokenId) external;
    event Transfer(address from, address to, uint256 tokenId);
    event Approval(address owner, address approved, uint256 tokenId);
    function supportsInterface(bytes4 _interfaceID) external view returns (bool);
}
contract AccessControl {
    event ContractUpgrade(address newContract);
    address public ceoAddress;
    address public cfoAddress;
    address public cooAddress;
    bool public paused = false;
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
    modifier onlyCLevel() {
        require(
            msg.sender == cooAddress ||
            msg.sender == ceoAddress ||
            msg.sender == cfoAddress
        );
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
    function pause() external onlyCLevel whenNotPaused {
        paused = true;
    }
    function unpause() public onlyCEO whenPaused {
        paused = false;
    }
}
contract PetBase is AccessControl {
    event Birth(address owner, uint256 monsterId, uint256 genes);
    event Transfer(address from, address to, uint256 tokenId);
    struct Pet {
        uint256 genes;
        uint64 birthTime;     
        uint16 generation;
        uint16 grade;
        uint16 level;
        uint16 params;
        uint16 skills;
    }
    uint256 public secondsPerBlock = 15;
    Pet[] pets; 
    mapping (uint256 => address) public petIndexToOwner;
    mapping (address => uint256) ownershipTokenCount;
    mapping (uint256 => address) public petIndexToApproved;
    SaleClockAuction public saleAuction;
    function _transfer(address _from, address _to, uint256 _tokenId) internal {
        ownershipTokenCount[_to]++;
        petIndexToOwner[_tokenId] = _to;
        if (_from != address(0)) {
            ownershipTokenCount[_from]--;
            delete petIndexToApproved[_tokenId];
        }
        emit Transfer(_from, _to, _tokenId);
    }
    function _createPet(
        uint256 _generation,
        uint256 _genes,
        address _owner,
        uint256 _grade,
        uint256 _level,
        uint256 _params,
        uint256 _skills
    )
        internal
        returns (uint)
    {
        require(_generation == uint256(uint16(_generation)));
        uint16 cooldownIndex = uint16(_generation / 2);
        if (cooldownIndex > 13) {
            cooldownIndex = 13;
        }
        Pet memory _pet = Pet({
            genes: _genes,
            birthTime: uint64(now),            
            generation: uint16(_generation),
            grade: uint16(_grade), 
            level: uint16(_level), 
            params: uint16(_params),            
            skills: uint16(_skills)
        });
        uint256 newPetId = pets.push(_pet) - 1;
        require(newPetId == uint256(uint32(newPetId)));
        emit Birth(
            _owner,
            newPetId,
            _pet.genes
        );
        _transfer(0, _owner, newPetId);
        return newPetId;
    }
}
contract ERC721Metadata {
    function getMetadata(uint256 _tokenId, string) public pure returns (bytes32[4] buffer, uint256 count) {
        if (_tokenId == 1) {
            buffer[0] = "Hello World! :D";
            count = 15;
        } else if (_tokenId == 2) {
            buffer[0] = "I would definitely choose a medi";
            buffer[1] = "um length string.";
            count = 49;
        } else if (_tokenId == 3) {
            buffer[0] = "Lorem ipsum dolor sit amet, mi e";
            buffer[1] = "st accumsan dapibus augue lorem,";
            buffer[2] = " tristique vestibulum id, libero";
            buffer[3] = " suscipit varius sapien aliquam.";
            count = 128;
        }
    }
}
contract PetOwnership is PetBase, ERC721 {
    string public constant name = "CatsVsDogs";
    string public constant symbol = "CD";
    ERC721Metadata public erc721Metadata;
    bytes4 constant InterfaceSignature_ERC165 =
        bytes4(keccak256('supportsInterface(bytes4)'));
    bytes4 constant InterfaceSignature_ERC721 =
        bytes4(keccak256('name()')) ^
        bytes4(keccak256('symbol()')) ^
        bytes4(keccak256('totalSupply()')) ^
        bytes4(keccak256('balanceOf(address)')) ^
        bytes4(keccak256('ownerOf(uint256)')) ^
        bytes4(keccak256('approve(address,uint256)')) ^
        bytes4(keccak256('transfer(address,uint256)')) ^
        bytes4(keccak256('transferFrom(address,address,uint256)')) ^
        bytes4(keccak256('tokensOfOwner(address)')) ^
        bytes4(keccak256('tokenMetadata(uint256,string)'));
    function supportsInterface(bytes4 _interfaceID) external view returns (bool)
    {
        return ((_interfaceID == InterfaceSignature_ERC165) || (_interfaceID == InterfaceSignature_ERC721));
    }
    function setMetadataAddress(address _contractAddress) public onlyCEO {
        erc721Metadata = ERC721Metadata(_contractAddress);
    }
    function _owns(address _claimant, uint256 _tokenId) internal view returns (bool) {
        return petIndexToOwner[_tokenId] == _claimant;
    }
    function _approvedFor(address _claimant, uint256 _tokenId) internal view returns (bool) {
        return petIndexToApproved[_tokenId] == _claimant;
    }
    function _approve(uint256 _tokenId, address _approved) internal {
        petIndexToApproved[_tokenId] = _approved;
    }
    function balanceOf(address _owner) public view returns (uint256 count) {
        return ownershipTokenCount[_owner];
    }
    function transfer(
        address _to,
        uint256 _tokenId
    )
        external
        whenNotPaused
    {
        require(_to != address(0));
        require(_to != address(this));
        require(_to != address(saleAuction));
        require(_owns(msg.sender, _tokenId));
        _transfer(msg.sender, _to, _tokenId);
    }
    function approve(
        address _to,
        uint256 _tokenId
    )
        external
        whenNotPaused
    {
        require(_owns(msg.sender, _tokenId));
        _approve(_tokenId, _to);
        emit Approval(msg.sender, _to, _tokenId);
    }
    function transferFrom(
        address _from,
        address _to,
        uint256 _tokenId
    )
        external
        whenNotPaused
    {
        require(_to != address(0));
        require(_to != address(this));
        require(_approvedFor(msg.sender, _tokenId));
        require(_owns(_from, _tokenId));
        _transfer(_from, _to, _tokenId);
    }
    function totalSupply() public view returns (uint) {
        return pets.length - 1;
    }
    function ownerOf(uint256 _tokenId)
        external
        view
        returns (address owner)
    {
        owner = petIndexToOwner[_tokenId];
        require(owner != address(0));
    }
    function tokensOfOwner(address _owner) external view returns(uint256[] ownerTokens) {
        uint256 tokenCount = balanceOf(_owner);
        if (tokenCount == 0) {
            return new uint256[](0);
        } else {
            uint256[] memory result = new uint256[](tokenCount);
            uint256 totalCats = totalSupply();
            uint256 resultIndex = 0;
            uint256 catId;
            for (catId = 1; catId <= totalCats; catId++) {
                if (petIndexToOwner[catId] == _owner) {
                    result[resultIndex] = catId;
                    resultIndex++;
                }
            }
            return result;
        }
    }
    function _memcpy(uint _dest, uint _src, uint _len) private pure {
        for(; _len >= 32; _len -= 32) {
            assembly {
                mstore(_dest, mload(_src))
            }
            _dest += 32;
            _src += 32;
        }
        uint256 mask = 256 ** (32 - _len) - 1;
        assembly {
            let srcpart := and(mload(_src), not(mask))
            let destpart := and(mload(_dest), mask)
            mstore(_dest, or(destpart, srcpart))
        }
    }
    function _toString(bytes32[4] _rawBytes, uint256 _stringLength) private pure returns (string) {
        string memory outputString = new string(_stringLength);
        uint256 outputPtr;
        uint256 bytesPtr;
        assembly {
            outputPtr := add(outputString, 32)
            bytesPtr := _rawBytes
        }
        _memcpy(outputPtr, bytesPtr, _stringLength);
        return outputString;
    }
    function tokenMetadata(uint256 _tokenId, string _preferredTransport) external view returns (string infoUrl) {
        require(erc721Metadata != address(0));
        bytes32[4] memory buffer;
        uint256 count;
        (buffer, count) = erc721Metadata.getMetadata(_tokenId, _preferredTransport);
        return _toString(buffer, count);
    }
}	
contract ClockAuctionBase {
    struct Auction {
        address seller;
        uint128 startingPrice;
        uint128 endingPrice;
        uint64 duration;
        uint64 startedAt;
    }
    ERC721 public nonFungibleContract;
    uint256 public ownerCut;
    mapping (uint256 => Auction) tokenIdToAuction;
    event AuctionCreated(uint256 tokenId, uint256 startingPrice, uint256 endingPrice, uint256 duration);
    event AuctionSuccessful(uint256 tokenId, uint256 totalPrice, address winner);
    event AuctionCancelled(uint256 tokenId);
    function _owns(address _claimant, uint256 _tokenId) internal view returns (bool) {
        return (nonFungibleContract.ownerOf(_tokenId) == _claimant);
    }
    function _escrow(address _owner, uint256 _tokenId) internal {
        nonFungibleContract.transferFrom(_owner, this, _tokenId);
    }
    function _transfer(address _receiver, uint256 _tokenId) internal {
        nonFungibleContract.transfer(_receiver, _tokenId);
    }
    function _addAuction(uint256 _tokenId, Auction _auction) internal {
        require(_auction.duration >= 1 minutes);
        tokenIdToAuction[_tokenId] = _auction;
        emit AuctionCreated(
            uint256(_tokenId),
            uint256(_auction.startingPrice),
            uint256(_auction.endingPrice),
            uint256(_auction.duration)
        );
    }
    function _cancelAuction(uint256 _tokenId, address _seller) internal {
        _removeAuction(_tokenId);
        _transfer(_seller, _tokenId);
        emit AuctionCancelled(_tokenId);
    }
    function _bid(uint256 _tokenId, uint256 _bidAmount)
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
            uint256 auctioneerCut = _computeCut(price);
            uint256 sellerProceeds = price - auctioneerCut;
            seller.transfer(sellerProceeds);
        }
        uint256 bidExcess = _bidAmount - price;
        msg.sender.transfer(bidExcess);
        emit AuctionSuccessful(_tokenId, price, msg.sender);
        return price;
    }
    function _removeAuction(uint256 _tokenId) internal {
        delete tokenIdToAuction[_tokenId];
    }
    function _isOnAuction(Auction storage _auction) internal view returns (bool) {
        return (_auction.startedAt > 0);
    }
    function _currentPrice(Auction storage _auction)
        internal
        view
        returns (uint256)
    {
        uint256 secondsPassed = 0;
        if (now > _auction.startedAt) {
            secondsPassed = now - _auction.startedAt;
        }
        return _computeCurrentPrice(
            _auction.startingPrice,
            _auction.endingPrice,
            _auction.duration,
            secondsPassed
        );
    }
    function _computeCurrentPrice(
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
    function _computeCut(uint256 _price) internal view returns (uint256) {
        return _price * ownerCut / 10000;
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
    modifier whenPaused {
        require(paused);
        _;
    }
    function pause() onlyOwner whenNotPaused public returns (bool) {
        paused = true;
        emit Pause();
        return true;
    }
    function unpause() onlyOwner whenPaused public returns (bool) {
        paused = false;
        emit Unpause();
        return true;
    }
}
contract ClockAuction is Pausable, ClockAuctionBase {
    bytes4 constant InterfaceSignature_ERC721 = bytes4(0x9a20483d);
    constructor (address _nftAddress, uint256 _cut) public {    
        require(_cut <= 10000);
        ownerCut = _cut;
        ERC721 candidateContract = ERC721(_nftAddress);
        require(candidateContract.supportsInterface(InterfaceSignature_ERC721));
        nonFungibleContract = candidateContract;
    }
    function withdrawBalance() external {
        address nftAddress = address(nonFungibleContract);
        require(
            msg.sender == owner ||
            msg.sender == nftAddress
        );
        uint256 balance = address(this).balance;
        nftAddress.transfer(balance);
    }
    function createAuction(
        uint256 _tokenId,
        uint256 _startingPrice,
        uint256 _endingPrice,
        uint256 _duration,
        address _seller
    )
        external
        whenNotPaused
    {
        require(_startingPrice == uint256(uint128(_startingPrice)));
        require(_endingPrice == uint256(uint128(_endingPrice)));
        require(_duration == uint256(uint64(_duration)));
        require(_owns(msg.sender, _tokenId));
        _escrow(msg.sender, _tokenId);
        Auction memory auction = Auction(
            _seller,
            uint128(_startingPrice),
            uint128(_endingPrice),
            uint64(_duration),
            uint64(now)
        );
        _addAuction(_tokenId, auction);
    }
    function bid(uint256 _tokenId)
        external
        payable
        whenNotPaused
    {
        _bid(_tokenId, msg.value);
        _transfer(msg.sender, _tokenId);
    }
    function cancelAuction(uint256 _tokenId)
        external
    {
        Auction storage auction = tokenIdToAuction[_tokenId];
        require(_isOnAuction(auction));
        address seller = auction.seller;
        require(msg.sender == seller);
        _cancelAuction(_tokenId, seller);
    }
    function cancelAuctionWhenPaused(uint256 _tokenId)
        whenPaused
        onlyOwner
        external
    {
        Auction storage auction = tokenIdToAuction[_tokenId];
        require(_isOnAuction(auction));
        _cancelAuction(_tokenId, auction.seller);
    }
    function getAuction(uint256 _tokenId)
        external
        view
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
    function getCurrentPrice(uint256 _tokenId)
        external
        view
        returns (uint256)
    {
        Auction storage auction = tokenIdToAuction[_tokenId];
        require(_isOnAuction(auction));
        return _currentPrice(auction);
    }
}
contract SaleClockAuction is ClockAuction {
    bool public isSaleClockAuction = true;
    uint256 public gen0SaleCount;
    uint256[5] public lastGen0SalePrices;
    constructor (address _nftAddr, uint256 _cut) public
        ClockAuction(_nftAddr, _cut) {}
    function createAuction(
        uint256 _tokenId,
        uint256 _startingPrice,
        uint256 _endingPrice,
        uint256 _duration,
        address _seller
    )
        external
    {
        require(_startingPrice == uint256(uint128(_startingPrice)));
        require(_endingPrice == uint256(uint128(_endingPrice)));
        require(_duration == uint256(uint64(_duration)));
        require(msg.sender == address(nonFungibleContract));
        _escrow(_seller, _tokenId);
        Auction memory auction = Auction(
            _seller,
            uint128(_startingPrice),
            uint128(_endingPrice),
            uint64(_duration),
            uint64(now)
        );
        _addAuction(_tokenId, auction);
    }
    function bid(uint256 _tokenId)
        external
        payable
    {
        address seller = tokenIdToAuction[_tokenId].seller;
        uint256 price = _bid(_tokenId, msg.value);
        _transfer(msg.sender, _tokenId);
        if (seller == address(nonFungibleContract)) {
            lastGen0SalePrices[gen0SaleCount % 5] = price;
            gen0SaleCount++;
        }
    }
    function averageGen0SalePrice() external view returns (uint256) {
        uint256 sum = 0;
        for (uint256 i = 0; i < 5; i++) {
            sum += lastGen0SalePrices[i];
        }
        return sum / 5;
    }
}
contract PetAuction is PetOwnership {
    function setSaleAuctionAddress(address _address) external onlyCEO {
        SaleClockAuction candidateContract = SaleClockAuction(_address);
        require(candidateContract.isSaleClockAuction());
        saleAuction = candidateContract;
    }
    function createSaleAuction(
        uint256 _petId,
        uint256 _startingPrice,
        uint256 _endingPrice,
        uint256 _duration
    )
        external
        whenNotPaused
    {
        require(_owns(msg.sender, _petId));
        _approve(_petId, saleAuction);
        saleAuction.createAuction(
            _petId,
            _startingPrice,
            _endingPrice,
            _duration,
            msg.sender
        );
    }    
    function withdrawAuctionBalances() external onlyCLevel {
        saleAuction.withdrawBalance();
    }
}
contract PetMinting is PetAuction {
    uint256 public constant PROMO_CREATION_LIMIT = 5000;
    uint256 public constant GEN0_CREATION_LIMIT = 45000;
    uint256 public constant GEN0_STARTING_PRICE = 100 szabo; 
    uint256 public constant GEN0_AUCTION_DURATION = 14 days;
    uint256 public promoCreatedCount;
    uint256 public gen0CreatedCount;
    function createPromoPet(uint256 _genes, address _owner, uint256 _grade, uint256 _level, uint256 _params, uint256 _skills) external onlyCOO {
        address petOwner = _owner;
        if (petOwner == address(0)) {
            petOwner = cooAddress;
        }
        require(promoCreatedCount < PROMO_CREATION_LIMIT);
        promoCreatedCount++;
        _createPet(0, _genes, petOwner, _grade, _level, _params, _skills);
    }
    function createGen0Auction(uint256 _genes, uint256 _grade, uint256 _level, uint256 _params, uint256 _skills) external onlyCOO {
        require(gen0CreatedCount < GEN0_CREATION_LIMIT);
        uint256 petId = _createPet(0, _genes, address(this), _grade, _level, _params, _skills);
        _approve(petId, saleAuction);
        saleAuction.createAuction(
            petId,
            GEN0_STARTING_PRICE,
            0,
            GEN0_AUCTION_DURATION,
            address(this)
        );
        gen0CreatedCount++;
    }
}
contract PetCore is PetMinting {
    address public newContractAddress;
    constructor() public {
        paused = true;
        ceoAddress = msg.sender;
        cooAddress = msg.sender;
        _createPet(0, uint256(-1), address(0), uint256(-1), uint256(-1), uint256(-1), uint256(-1));
    }
    function setNewAddress(address _v2Address) external onlyCEO whenPaused {
        newContractAddress = _v2Address;
        emit ContractUpgrade(_v2Address);
    }
    function() external payable {
        require(
            msg.sender == address(saleAuction) 
        );
    }
    function getPet(uint256 _id)
        external
        view
        returns (
        uint256 birthTime,
        uint256 generation,
        uint256 genes,
        uint256 grade,
        uint256 level,
        uint256 params,
        uint256 skills
    ) {
        Pet storage pet = pets[_id];
        birthTime = uint256(pet.birthTime);
        generation = uint256(pet.generation);
        genes = pet.genes;
        grade = pet.grade;
        level = pet.level;
        params = pet.params;
        skills = pet.skills;
    }
    function unpause() public onlyCEO whenPaused {
        require(saleAuction != address(0));
        require(newContractAddress == address(0));
        super.unpause();
    }
    function withdrawBalance() external onlyCFO {
        uint256 balance = address(this).balance;
        cfoAddress.transfer(balance);        
    }
    function withdrawBalanceCut(uint256 amount) external onlyCFO {
        uint256 balance = address(this).balance;
        require (balance > amount);
        cfoAddress.transfer(amount);        
    }
}