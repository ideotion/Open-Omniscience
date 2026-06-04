"""
Instrument Fundamentals Model

Represents financial fundamentals for a financial instrument (primarily stocks/ETFs).
This replaces the original CompanyFundamentals model to support all instrument types.
Includes both dataclass and SQLAlchemy model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


@dataclass
class InstrumentFundamentals:
    """
    Fundamentals for financial instruments (primarily stocks/ETFs).
    
    Attributes:
        id: UUID for this fundamentals record
        instrument_id: Reference to the instrument
        date: Reporting date for these fundamentals
        fiscal_period: Fiscal period (e.g., "Q1", "Annual", "TTM")
        
        # Valuation metrics (stocks/ETFs)
        market_cap: Market capitalization
        pe_ratio: Price-to-Earnings ratio
        peg_ratio: PE-to-Growth ratio
        pb_ratio: Price-to-Book ratio
        ps_ratio: Price-to-Sales ratio
        
        # Profitability metrics (stocks/ETFs)
        eps: Earnings per share
        revenue: Revenue
        net_income: Net income
        profit_margin: Profit margin (as decimal, e.g., 0.15 = 15%)
        
        # Dividend metrics (stocks/ETFs)
        dividend_yield: Dividend yield (as decimal)
        
        # Risk metrics (stocks/ETFs)
        beta: Beta coefficient
        debt_to_equity: Debt-to-equity ratio
        current_ratio: Current ratio
        roe: Return on equity (as decimal)
        roa: Return on assets (as decimal)
        
        # Commodity-specific metrics
        contract_size: Contract size (e.g., 100 troy oz for gold)
        tick_size: Minimum price movement
        
        # Crypto-specific metrics
        max_supply: Maximum supply (for crypto)
        circulating_supply: Circulating supply
        
        # Metadata
        currency: Currency of the values
        source: Data source
        created_at: When this record was added to the system
    """
    id: str
    instrument_id: str
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
    
    # Commodity-specific metrics
    contract_size: Optional[float] = None
    tick_size: Optional[float] = None
    
    # Crypto-specific metrics
    max_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    
    # Metadata
    currency: str = "USD"
    source: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate fundamentals data."""
        if not self.id:
            raise ValueError("Fundamentals ID cannot be empty")
        if not self.instrument_id:
            raise ValueError("Instrument ID cannot be empty")
        if not self.date:
            raise ValueError("Date cannot be empty")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
    
    @property
    def is_profitable(self) -> Optional[bool]:
        """Check if instrument is profitable."""
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
            "instrument_id": self.instrument_id,
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
            
            # Commodity-specific
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            
            # Crypto-specific
            "max_supply": self.max_supply,
            "circulating_supply": self.circulating_supply,
            
            # Metadata
            "currency": self.currency,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            
            # Computed
            "is_profitable": self.is_profitable,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstrumentFundamentals":
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
            instrument_id=data.get("instrument_id") or data.get("company_id"),  # Backward compatibility
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
            contract_size=data.get("contract_size"),
            tick_size=data.get("tick_size"),
            max_supply=data.get("max_supply"),
            circulating_supply=data.get("circulating_supply"),
            currency=data.get("currency", "USD"),
            source=data.get("source"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"InstrumentFundamentals(id={self.id!r}, instrument_id={self.instrument_id!r}, date={self.date!r})"


# SQLAlchemy model
class InstrumentFundamentalsDB(Base):
    """SQLAlchemy model for the instrument_fundamentals table."""
    __tablename__ = 'instrument_fundamentals'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    date = Column(DateTime, nullable=False)
    fiscal_period = Column(String(20), default="TTM")
    
    # Valuation metrics
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    peg_ratio = Column(Float)
    pb_ratio = Column(Float)
    ps_ratio = Column(Float)
    
    # Profitability metrics
    eps = Column(Float)
    revenue = Column(Float)
    net_income = Column(Float)
    profit_margin = Column(Float)
    
    # Dividend metrics
    dividend_yield = Column(Float)
    
    # Risk metrics
    beta = Column(Float)
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    
    # Commodity-specific metrics
    contract_size = Column(Float)
    tick_size = Column(Float)
    
    # Crypto-specific metrics
    max_supply = Column(Float)
    circulating_supply = Column(Float)
    
    # Metadata
    currency = Column(String(3), default="USD")
    source = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="fundamentals")
    
    # Indexes
    __table_args__ = (
        Index('idx_fundamentals_instrument', 'instrument_id'),
        Index('idx_fundamentals_date', 'date'),
        Index('idx_fundamentals_instrument_date', 'instrument_id', 'date'),
    )
    
    def to_dataclass(self) -> InstrumentFundamentals:
        """Convert SQLAlchemy model to dataclass."""
        return InstrumentFundamentals(
            id=self.id,
            instrument_id=self.instrument_id,
            date=self.date,
            fiscal_period=self.fiscal_period,
            market_cap=self.market_cap,
            pe_ratio=self.pe_ratio,
            peg_ratio=self.peg_ratio,
            pb_ratio=self.pb_ratio,
            ps_ratio=self.ps_ratio,
            eps=self.eps,
            revenue=self.revenue,
            net_income=self.net_income,
            profit_margin=self.profit_margin,
            dividend_yield=self.dividend_yield,
            beta=self.beta,
            debt_to_equity=self.debt_to_equity,
            current_ratio=self.current_ratio,
            roe=self.roe,
            roa=self.roa,
            contract_size=self.contract_size,
            tick_size=self.tick_size,
            max_supply=self.max_supply,
            circulating_supply=self.circulating_supply,
            currency=self.currency,
            source=self.source,
            created_at=self.created_at,
        )
    
    @classmethod
    def from_dataclass(cls, fundamentals: InstrumentFundamentals) -> "InstrumentFundamentalsDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=fundamentals.id,
            instrument_id=fundamentals.instrument_id,
            date=fundamentals.date,
            fiscal_period=fundamentals.fiscal_period,
            market_cap=fundamentals.market_cap,
            pe_ratio=fundamentals.pe_ratio,
            peg_ratio=fundamentals.peg_ratio,
            pb_ratio=fundamentals.pb_ratio,
            ps_ratio=fundamentals.ps_ratio,
            eps=fundamentals.eps,
            revenue=fundamentals.revenue,
            net_income=fundamentals.net_income,
            profit_margin=fundamentals.profit_margin,
            dividend_yield=fundamentals.dividend_yield,
            beta=fundamentals.beta,
            debt_to_equity=fundamentals.debt_to_equity,
            current_ratio=fundamentals.current_ratio,
            roe=fundamentals.roe,
            roa=fundamentals.roa,
            contract_size=fundamentals.contract_size,
            tick_size=fundamentals.tick_size,
            max_supply=fundamentals.max_supply,
            circulating_supply=fundamentals.circulating_supply,
            currency=fundamentals.currency,
            source=fundamentals.source,
            created_at=fundamentals.created_at,
        )
