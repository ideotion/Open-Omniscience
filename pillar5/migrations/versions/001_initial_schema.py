"""
Pillar 5: Initial Schema Migration

This migration creates all the initial tables for Pillar 5's financial intelligence system:
- financial_exchanges
- financial_instruments
- financial_data_points
- instrument_fundamentals
- financial_analyses
- article_financial_links
- financial_metrics
- instrument_keywords

Note: The 'articles' table is managed by the main Open-Omniscience database and is referenced via ForeignKey.
"""

from alembic import op, context
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# Alembic revision identifier
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


# Helper function to handle SQLite-specific operations
def _create_index(table_name, column_names, unique=False, name=None):
    """Create an index with proper naming."""
    if name is None:
        name = f"idx_{table_name}_{'_'.join(column_names)}"
    op.create_index(name, table_name, column_names, unique=unique)


def upgrade():
    """Create all Pillar 5 tables."""
    
    # Create financial_exchanges table
    op.create_table(
        'financial_exchanges',
        sa.Column('id', sa.String(10), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('country', sa.String(2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('timezone', sa.String(50), nullable=False),
        sa.Column('website', sa.String(500)),
        sa.Column('trading_hours', sa.String(100)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_scraped', sa.DateTime),
        sa.Column('extra_metadata', sa.JSON),
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
        sa.Column('updated_at', sa.DateTime, default=sa.func.datetime('now'), onupdate=sa.func.datetime('now')),
    )
    
    # Create indexes for financial_exchanges
    _create_index('financial_exchanges', ['country'])
    _create_index('financial_exchanges', ['currency'])
    
    # Create financial_instruments table
    op.create_table(
        'financial_instruments',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('symbol', sa.String(20), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, index=True),  # stock, etf, index, commodity, forex, crypto
        sa.Column('exchange_id', sa.String(10), sa.ForeignKey('financial_exchanges.id')),
        sa.Column('sector', sa.String(100), index=True),
        sa.Column('industry', sa.String(100), index=True),
        sa.Column('category', sa.String(100)),
        sa.Column('base_currency', sa.String(3), default='USD'),
        sa.Column('quote_currency', sa.String(3)),  # For forex/crypto
        sa.Column('description', sa.Text),
        sa.Column('founded_year', sa.Integer),
        sa.Column('headquarters', sa.String(255)),
        sa.Column('website', sa.String(500)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_updated', sa.DateTime),
        sa.Column('extra_metadata', sa.JSON),
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
        sa.Column('updated_at', sa.DateTime, default=sa.func.datetime('now'), onupdate=sa.func.datetime('now')),
    )
    
    # Create indexes for financial_instruments
    op.create_index('idx_instrument_symbol_type', 'financial_instruments', ['symbol', 'type'], unique=True)
    _create_index('financial_instruments', ['type'])
    _create_index('financial_instruments', ['sector'])
    _create_index('financial_instruments', ['industry'])
    _create_index('financial_instruments', ['exchange_id'])
    
    # Create financial_data_points table
    op.create_table(
        'financial_data_points',
        sa.Column('id', sa.String(36), primary_key=True),  # UUID
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id'), nullable=False),
        sa.Column('timestamp', sa.DateTime, nullable=False),
        sa.Column('open', sa.Float),
        sa.Column('high', sa.Float),
        sa.Column('low', sa.Float),
        sa.Column('close', sa.Float),
        sa.Column('adjusted_close', sa.Float),
        sa.Column('volume', sa.Float),  # Use Float for crypto/forex volumes
        sa.Column('currency', sa.String(3), default='USD'),
        sa.Column('is_dividend_adjusted', sa.Boolean, default=False),
        sa.Column('data_source', sa.String(100)),  # e.g., "yahoo_finance", "investing_com"
        sa.Column('extra_metadata', sa.JSON),  # e.g., {"split_factor": 2.0, "dividend": 0.5}
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
    )
    
    # Create indexes for financial_data_points
    _create_index('financial_data_points', ['instrument_id'])
    _create_index('financial_data_points', ['timestamp'])
    _create_index('financial_data_points', ['instrument_id', 'timestamp'])
    
    # Create instrument_fundamentals table
    op.create_table(
        'instrument_fundamentals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id'), nullable=False),
        sa.Column('date', sa.DateTime, nullable=False),
        sa.Column('fiscal_period', sa.String(20), default='TTM'),
        
        # Valuation metrics
        sa.Column('market_cap', sa.Float),
        sa.Column('pe_ratio', sa.Float),
        sa.Column('peg_ratio', sa.Float),
        sa.Column('pb_ratio', sa.Float),
        sa.Column('ps_ratio', sa.Float),
        
        # Profitability metrics
        sa.Column('eps', sa.Float),
        sa.Column('revenue', sa.Float),
        sa.Column('net_income', sa.Float),
        sa.Column('profit_margin', sa.Float),
        
        # Dividend metrics
        sa.Column('dividend_yield', sa.Float),
        
        # Risk metrics
        sa.Column('beta', sa.Float),
        sa.Column('debt_to_equity', sa.Float),
        sa.Column('current_ratio', sa.Float),
        sa.Column('roe', sa.Float),
        sa.Column('roa', sa.Float),
        
        # Commodity-specific metrics
        sa.Column('contract_size', sa.Float),
        sa.Column('tick_size', sa.Float),
        
        # Crypto-specific metrics
        sa.Column('max_supply', sa.Float),
        sa.Column('circulating_supply', sa.Float),
        
        # Metadata
        sa.Column('currency', sa.String(3), default='USD'),
        sa.Column('source', sa.String(100)),
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
    )
    
    # Create indexes for instrument_fundamentals
    _create_index('instrument_fundamentals', ['instrument_id'])
    _create_index('instrument_fundamentals', ['date'])
    _create_index('instrument_fundamentals', ['instrument_id', 'date'])
    
    # Create financial_analyses table
    op.create_table(
        'financial_analyses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id')),
        sa.Column('exchange_id', sa.String(10), sa.ForeignKey('financial_exchanges.id')),
        sa.Column('analysis_type', sa.String(20), nullable=False),
        sa.Column('analysis_date', sa.DateTime, default=sa.func.datetime('now')),
        sa.Column('time_period', sa.String(10), default='1D'),
        
        # Results (JSON)
        sa.Column('results', sa.JSON),
        
        # Metadata
        sa.Column('confidence', sa.Float, default=0.0),
        sa.Column('severity', sa.String(20), default='medium'),
        sa.Column('related_articles', sa.JSON, default=[]),
        sa.Column('related_events', sa.JSON, default=[]),
        
        # Type-specific fields
        sa.Column('price_change_pct', sa.Float),
        sa.Column('volume_change_pct', sa.Float),
        sa.Column('volatility', sa.Float),
        sa.Column('pattern_type', sa.String(50)),
        sa.Column('pattern_strength', sa.Float),
        sa.Column('correlation_score', sa.Float),
        sa.Column('correlated_article_ids', sa.JSON, default=[]),
        
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
    )
    
    # Create indexes for financial_analyses
    _create_index('financial_analyses', ['instrument_id'])
    _create_index('financial_analyses', ['analysis_type'])
    _create_index('financial_analyses', ['analysis_date'])
    _create_index('financial_analyses', ['instrument_id', 'analysis_type'])
    
    # Create article_financial_links table
    op.create_table(
        'article_financial_links',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('article_id', sa.String(36), sa.ForeignKey('articles.id'), nullable=False),
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id')),
        sa.Column('exchange_id', sa.String(10), sa.ForeignKey('financial_exchanges.id')),
        
        # Correlation metadata
        sa.Column('correlation_score', sa.Float, default=0.0),
        sa.Column('correlation_type', sa.String(20), default='mention'),
        sa.Column('time_diff_hours', sa.Float),
        sa.Column('direction', sa.String(20), default='same_time'),
        
        # Keyword matching (new for hybrid linking)
        sa.Column('matched_keywords', sa.JSON, default=[]),
        sa.Column('matched_sector', sa.String(100)),
        
        # Sentiment analysis
        sa.Column('article_sentiment', sa.Float),
        sa.Column('financial_sentiment', sa.Float),
        
        # Analysis
        sa.Column('is_significant', sa.Boolean, default=False),
        sa.Column('confidence', sa.Float, default=0.0),
        
        # Metadata
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
        sa.Column('updated_at', sa.DateTime, default=sa.func.datetime('now'), onupdate=sa.func.datetime('now')),
    )
    
    # Create indexes for article_financial_links
    _create_index('article_financial_links', ['article_id'])
    _create_index('article_financial_links', ['instrument_id'])
    _create_index('article_financial_links', ['correlation_type'])
    _create_index('article_financial_links', ['correlation_score'])
    _create_index('article_financial_links', ['article_id', 'instrument_id'])
    
    # Create financial_metrics table
    op.create_table(
        'financial_metrics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id'), nullable=False),
        sa.Column('metric_name', sa.String(100), nullable=False),
        sa.Column('metric_group', sa.String(50), nullable=False),  # Trend, Momentum, Volatility, Volume, Fundamental, Statistical, Pattern, Custom
        sa.Column('metric_value', sa.Float, nullable=False),
        sa.Column('timeframe', sa.String(10), default='1D'),  # 1D, 1W, 1M, 3M, 1Y, etc.
        sa.Column('timestamp', sa.DateTime, nullable=False),
        sa.Column('calculation_method', sa.String(255), nullable=False),
        sa.Column('parameters', sa.JSON, default={}),  # e.g., {"period": 20}
        sa.Column('source', sa.String(100)),
        sa.Column('is_real_time', sa.Boolean, default=False),
        sa.Column('confidence', sa.Float, default=1.0),
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
        sa.Column('updated_at', sa.DateTime, default=sa.func.datetime('now'), onupdate=sa.func.datetime('now')),
    )
    
    # Create indexes for financial_metrics
    _create_index('financial_metrics', ['instrument_id'])
    _create_index('financial_metrics', ['metric_name'])
    _create_index('financial_metrics', ['metric_group'])
    _create_index('financial_metrics', ['timestamp'])
    _create_index('financial_metrics', ['instrument_id', 'timestamp'])
    _create_index('financial_metrics', ['instrument_id', 'metric_group'])
    
    # Create instrument_keywords table
    op.create_table(
        'instrument_keywords',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('instrument_id', sa.String(50), sa.ForeignKey('financial_instruments.id'), nullable=False),
        sa.Column('keyword', sa.String(100), nullable=False),
        sa.Column('source', sa.String(20), default='name'),  # name, description, sector, article
        sa.Column('weight', sa.Float, default=1.0),
        sa.Column('language', sa.String(10), default='en'),
        sa.Column('created_at', sa.DateTime, default=sa.func.datetime('now')),
    )
    
    # Create indexes for instrument_keywords
    _create_index('instrument_keywords', ['instrument_id'])
    _create_index('instrument_keywords', ['keyword'])
    _create_index('instrument_keywords', ['source'])
    _create_index('instrument_keywords', ['instrument_id', 'keyword'])


def downgrade():
    """Drop all Pillar 5 tables."""
    op.drop_table('instrument_keywords')
    op.drop_table('financial_metrics')
    op.drop_table('article_financial_links')
    op.drop_table('financial_analyses')
    op.drop_table('instrument_fundamentals')
    op.drop_table('financial_data_points')
    op.drop_table('financial_instruments')
    op.drop_table('financial_exchanges')
