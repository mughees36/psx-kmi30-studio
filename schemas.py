from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    password: str
    phone: str

class UserLogin(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    id: int
    email: str
    phone: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class UserProfile(BaseModel):
    id: int
    email: str
    phone: str


class StockListItem(BaseModel):
    symbol: str
    name: str
    ldcp: float
    current: float
    change: float
    change_percent: float
    idx_weight_percent: float
    idx_points: float
    volume: int
    freefloat_mn: float
    market_cap_mn: float


class FavoriteStocksResponse(BaseModel):
    symbols: list[str]
    stocks: list["StockListItem"]


class ChartSeries(BaseModel):
    labels: list[str]
    values: list[float]
    title: str


class HistoricalPricePoint(BaseModel):
    timestamp: int
    label: str
    close: float
    open: float | None = None
    volume: int | None = None


class HistoricalPriceData(BaseModel):
    intraday: list[HistoricalPricePoint]
    eod: list[HistoricalPricePoint]
    default_range: str = "1M"


class StockMetric(BaseModel):
    label: str
    value: str


class FinancialRow(BaseModel):
    label: str
    values: list[str]


class FinancialTable(BaseModel):
    periods: list[str]
    rows: list[FinancialRow]


class AnnouncementItem(BaseModel):
    date: str
    title: str
    document_url: str | None = None


class DividendHistoryItem(BaseModel):
    date: str
    period: str
    details: str
    book_closure: str
    dividend_amount: str | None = None


class StockDetail(BaseModel):
    symbol: str
    name: str
    sector: str
    current_price: float
    absolute_change: float
    percent_change: float
    as_of: str
    business_description: str
    address: str
    website: str
    registrar: str
    auditor: str
    fiscal_year_end: str
    key_people: list[str]
    quote_metrics: list[StockMetric]
    equity_profile: list[StockMetric]
    fundamentals: list[StockMetric]
    sector_average_pe: float | None = None
    sector_pe_peer_count: int = 0
    sector_pe_method: str | None = None
    peer_companies: list[str]
    valuation_eps: float | None = None
    fair_price: float | None = None
    dividend_history: list[DividendHistoryItem]
    announcements: list[AnnouncementItem]
    annual_financials: FinancialTable
    quarterly_financials: FinancialTable
    ratios: FinancialTable
    price_chart: ChartSeries
    historical_prices: HistoricalPriceData
    financial_chart: ChartSeries
    ratio_chart: ChartSeries
