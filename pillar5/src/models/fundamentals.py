"""
Company Fundamentals Model

Represents financial fundamentals for a company.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class CompanyFundamentals:
    """
    Represents financial fundamentals for a company.
    
    Attributes:
        id: UUID for this fundamentals record
        company_id: Reference to the company
        date: Reporting date for these fundamentals
        fiscal_period: Fiscal period (e.g., "Q1", "Annual", "TTM")
        
        # Valuation metrics
        market_cap: Market capitalization
        pe_ratio: Price-to-Earnings ratio
        peg_ratio: PE-to-Growth ratio
        pb_ratio: Price-to-Book ratio
        ps_ratio: Price-to-Sales ratio
        
        # Profitability metrics
        eps: Earnings per share
        revenue: Revenue
        net_income: Net income
        profit_margin: Profit margin (as decimal, e.g., 0.15 = 15%)
        
        # Dividend metrics
        dividend_yield: Dividend yield (as decimal)
        
        # Risk metrics
        beta: Beta coefficient
        debt_to_equity: Debt-to-equity ratio
        current_ratio: Current ratio
        roe: Return on equity (as decimal)
        roa: Return on assets (as decimal)
        
        # Metadata
        currency: Currency of the values
        source: Data source
        created_at: When this record was added to the system
    """
    id: str
    company_id: str
    date: datetime
    fiscal_period: str = "TTM"
    
    # Valuation metrics
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    
    # Profitability metrics
    eps: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    profit_margin: Optional[float] = None
    
    # Dividend metrics
    dividend_yield: Optional[float] = None
    
    # Risk metrics
    beta: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    
    # Metadata
    currency: str = "USD"
    source: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate fundamentals data."""
        if not self.id:
            raise ValueError("Fundamentals ID cannot be empty")
        if not self.company_id:
            raise ValueError("Company ID cannot be empty")
        if not self.date:
            raise ValueError("Date cannot be empty")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
    
    @property
    def is_profitable(self) -> Optional[bool]:
        """Check if company is profitable."""
        if self.net_income is not None:
            return self.net_income > 0
        return None
    
    @property
    def profitability_summary(self) -> Dict[str, Any]:
        """Get a summary of profitability metrics."""
        return {
            "is_profitable": self.is_profitable,
            "profit_margin_pct": (self.profit_margin * 100) if self.profit_margin else None,
            "roe_pct": (self.roe * 100) if self.roe else None,
            "roa_pct": (self.roa * 100) if self.roa else None,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert fundamentals to dictionary."""
        return {
            "id": self.id,
            "company_id": self.company_id,
            "date": self.date.isoformat(),
            "fiscal_period": self.fiscal_period,
            
            # Valuation
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "peg_ratio": self.peg_ratio,
            "pb_ratio": self.pb_ratio,
            "ps_ratio": self.ps_ratio,
            
            # Profitability
            "eps": self.eps,
            "revenue": self.revenue,
            "net_income": self.net_income,
            "profit_margin": self.profit_margin,
            "profit_margin_pct": (self.profit_margin * 100) if self.profit_margin else None,
            
            # Dividends
            "dividend_yield": self.dividend_yield,
            "dividend_yield_pct": (self.dividend_yield * 100) if self.dividend_yield else None,
            
            # Risk
            "beta": self.beta,
            "debt_to_equity": self.debt_to_equity,
            "current_ratio": self.current_ratio,
            "roe": self.roe,
            "roe_pct": (self.roe * 100) if self.roe else None,
            "roa": self.roa,
            "roa_pct": (self.roa * 100) if self.roa else None,
            
            # Metadata
            "currency": self.currency,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            
            # Computed
            "is_profitable": self.is_profitable,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyFundamentals":
        """Create fundamentals from dictionary."""
        # Convert percentage fields back to decimals
        profit_margin = data.get("profit_margin")
        if profit_margin is not None and profit_margin > 1:
            profit_margin = profit_margin / 100
        
        dividend_yield = data.get("dividend_yield")
        if dividend_yield is not None and dividend_yield > 1:
            dividend_yield = dividend_yield / 100
        
        roe = data.get("roe")
        if roe is not None and roe > 1:
            roe = roe / 100
        
        roa = data.get("roa")
        if roa is not None and roa > 1:
            roa = roa / 100
        
        return cls(
            id=data.get("id"),
            company_id=data.get("company_id"),
            date=datetime.fromisoformat(data["date"]) if data.get("date") else datetime.utcnow(),
            fiscal_period=data.get("fiscal_period", "TTM"),
            market_cap=data.get("market_cap"),
            pe_ratio=data.get("pe_ratio"),
            peg_ratio=data.get("peg_ratio"),
            pb_ratio=data.get("pb_ratio"),
            ps_ratio=data.get("ps_ratio"),
            eps=data.get("eps"),
            revenue=data.get("revenue"),
            net_income=data.get("net_income"),
            profit_margin=profit_margin,
            dividend_yield=dividend_yield,
            beta=data.get("beta"),
            debt_to_equity=data.get("debt_to_equity"),
            current_ratio=data.get("current_ratio"),
            roe=roe,
            roa=roa,
            currency=data.get("currency", "USD"),
            source=data.get("source"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"CompanyFundamentals(id={self.id!r}, company_id={self.company_id!r}, date={self.date!r})"
