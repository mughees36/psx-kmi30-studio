import json
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = ssl.create_default_context()


PSX_INDEX_URL = "https://dps.psx.com.pk/indices/KMI30"
PSX_COMPANY_URL = "https://dps.psx.com.pk/company/{symbol}"
PSX_SECTOR_SUMMARY_URL = "https://dps.psx.com.pk/sector-summary/sectorwise"
PSX_TIMESERIES_URL = "https://dps.psx.com.pk/timeseries/{series_type}/{symbol}"
PSX_PAYOUTS_URL = "https://dps.psx.com.pk/company/payouts"
STOCK_ANALYSIS_INCOME_URL = "https://stockanalysis.com/quote/psx/{symbol}/financials/"
STOCK_ANALYSIS_BALANCE_URL = "https://stockanalysis.com/quote/psx/{symbol}/financials/balance-sheet/"
STOCK_ANALYSIS_CASHFLOW_URL = "https://stockanalysis.com/quote/psx/{symbol}/financials/cash-flow-statement/"
STOCK_ANALYSIS_DIVIDEND_URL = "https://stockanalysis.com/quote/psx/{symbol}/dividend/"
CACHE_TTL_SECONDS = 300
CORPORATE_ACTION_MARKERS = {"XD", "XR", "XE", "XB", "XC", "XT", "XA", "XW"}
HIDDEN_QUOTE_METRICS = {"Ask Price", "Ask Volume", "Bid Price", "Bid Volume", "HAIRCUT"}


class PSXServiceError(Exception):
    pass


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table = []
        self._current_row = []
        self._cell_chunks = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_chunks = []

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._in_cell:
            value = " ".join(chunk for chunk in self._cell_chunks if chunk).strip()
            self._current_row.append(value)
            self._in_cell = False
            self._cell_chunks = []
        elif tag == "tr" and self._in_row:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            cleaned = " ".join(data.split())
            if cleaned:
                self._cell_chunks.append(cleaned)


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._ignored_depth = 0
        self.lines = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth:
            return

        cleaned = " ".join(data.split()).strip()
        if cleaned:
            self.lines.append(cleaned)


_cache = {}
_snapshot_cache = {}
_sector_company_cache = {}
_company_valuation_cache = {}
_sector_valuation_cache = {}
_post_cache = {}
_statement_cache = {}
_kmi30_index_cache = {}


def _fetch_html(url: str) -> str:
    cached = _cache.get(url)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["html"]

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    try:
        with urlopen(request, timeout=20, context=_SSL_CONTEXT) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except URLError as exc:
        raise PSXServiceError("Could not reach official PSX data right now.") from exc

    _cache[url] = {"timestamp": now, "html": html}
    return html


def _post_form_html(url: str, form_data: dict[str, str]) -> str:
    cache_key = (url, tuple(sorted(form_data.items())))
    cached = _post_cache.get(cache_key)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["html"]

    encoded_data = urlencode(form_data).encode()
    request = Request(
        url,
        data=encoded_data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    try:
        with urlopen(request, timeout=20, context=_SSL_CONTEXT) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except URLError as exc:
        raise PSXServiceError("Could not reach official PSX data right now.") from exc

    _post_cache[cache_key] = {"timestamp": now, "html": html}
    return html


def _parse_tables(html: str):
    parser = TableParser()
    parser.feed(html)
    return parser.tables


def _visible_lines(html: str):
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.lines


def _to_float(value: str) -> float:
    cleaned = value.replace("Rs.", "").replace(",", "").replace("%", "").strip()
    cleaned = cleaned.replace("—", "-")
    if cleaned.startswith("--"):
        cleaned = f"-{cleaned[2:]}"
    if cleaned.startswith("(") and cleaned.endswith(")"):
        inner = cleaned[1:-1].strip()
        inner = inner.lstrip("+-")
        cleaned = f"-{inner}"
    return float(cleaned)


def _to_int(value: str) -> int:
    return int(float(value.replace(",", "").strip()))


def _safe_to_float(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        return _to_float(value)
    except (TypeError, ValueError):
        return None


def _find_first_table_with_headers(tables, headers):
    for table in tables:
        if not table:
            continue
        normalized = [cell.upper() for cell in table[0]]
        if all(any(header.upper() in cell for cell in normalized) for header in headers):
            return table
    raise PSXServiceError("Official PSX table structure changed and could not be parsed.")


def get_kmi30_stocks():
    html = _fetch_html(PSX_INDEX_URL)
    table = _find_first_table_with_headers(_parse_tables(html), ["SYMBOL", "NAME", "CURRENT", "VOLUME"])
    rows = []

    for row in table[1:]:
        if len(row) < 11:
            continue

        rows.append(
            {
                "symbol": row[0],
                "name": row[1],
                "ldcp": _to_float(row[2]),
                "current": _to_float(row[3]),
                "change": _to_float(row[4]),
                "change_percent": _to_float(row[5]),
                "idx_weight_percent": _to_float(row[6]),
                "idx_points": _to_float(row[7]),
                "volume": _to_int(row[8]),
                "freefloat_mn": _to_float(row[9]),
                "market_cap_mn": _to_float(row[10]),
            }
        )

    if not rows:
        raise PSXServiceError("No KMI30 stocks were parsed from the official PSX page.")

    return rows


def get_kmi30_index():
    now = time.time()
    cached = _kmi30_index_cache.get("data")
    if cached and now - cached["timestamp"] < 60:
        return cached["value"]

    url = PSX_TIMESERIES_URL.format(series_type="eod", symbol="KMI30")
    html = _fetch_html(url)
    data = json.loads(html)
    points = data.get("data", [])

    if len(points) < 2:
        raise PSXServiceError("Not enough KMI30 index data available.")

    # points[0] = last completed session close; each: [timestamp, close, volume, open]
    last_eod_close = points[0][1]
    last_eod_timestamp = points[0][0]
    prev_close = points[1][1]

    # Determine if EOD has updated for today (market closed) or we're mid-session
    from datetime import datetime, timedelta
    pst_offset = timedelta(hours=5)
    today_pst = (datetime.utcnow() + pst_offset).date()
    last_eod_date = (datetime.utcfromtimestamp(last_eod_timestamp) + pst_offset).date()

    if last_eod_date < today_pst:
        # EOD hasn't updated yet — market is open intraday.
        # Derive live index by adding today's idx_points to the last EOD close.
        try:
            stocks = get_kmi30_stocks()
            idx_points_sum = sum(s["idx_points"] for s in stocks)
            today_level = round(last_eod_close + idx_points_sum, 2)
            change = round(idx_points_sum, 2)
        except Exception:
            today_level = last_eod_close
            change = round(last_eod_close - prev_close, 2)
        base_for_pct = last_eod_close
    else:
        # EOD has today's close already
        today_level = last_eod_close
        change = round(last_eod_close - prev_close, 2)
        base_for_pct = prev_close

    change_percent = round((change / base_for_pct) * 100, 2) if base_for_pct else 0.0

    result = {
        "level": today_level,
        "change": change,
        "change_percent": change_percent,
    }
    _kmi30_index_cache["data"] = {"timestamp": now, "value": result}
    return result


def _slice(lines, start_label, end_label):
    try:
        start = lines.index(start_label) + 1
    except ValueError as exc:
        raise PSXServiceError(f"Could not find {start_label} on the official PSX page.") from exc

    try:
        end = lines.index(end_label, start)
    except ValueError:
        end = len(lines)
    return lines[start:end]


def _next_value(lines, label, start_index=0):
    for index in range(start_index, len(lines)):
        if lines[index] == label and index + 1 < len(lines):
            return lines[index + 1]
    raise PSXServiceError(f"Could not find value for {label} on the official PSX page.")


def _parse_quote_metrics(lines):
    quote_start = lines.index("Open")
    quote_end = lines.index("Company Profile")
    quote_lines = lines[quote_start:quote_end]
    labels = [
        "Open",
        "High",
        "Low",
        "Volume",
        "CIRCUIT BREAKER",
        "DAY RANGE",
        "52-WEEK RANGE ^",
        "Ask Price",
        "Ask Volume",
        "Bid Price",
        "Bid Volume",
        "LDCP",
        "VAR",
        "HAIRCUT",
        "P/E Ratio (TTM) **",
        "1-Year Change * ^",
        "YTD Change * ^",
    ]

    metrics = []
    used = set()
    for label in labels:
        for index, line in enumerate(quote_lines):
            if line == label and label not in used and index + 1 < len(quote_lines):
                metrics.append({"label": label.replace(" ^", "").replace(" **", ""), "value": quote_lines[index + 1]})
                used.add(label)
                break
    return [metric for metric in metrics if metric["label"] not in HIDDEN_QUOTE_METRICS]


def _parse_key_people(profile_lines):
    try:
        start = profile_lines.index("KEY PEOPLE") + 1
        end = profile_lines.index("ADDRESS")
    except ValueError:
        return []
    return profile_lines[start:end]


def _parse_equity_profile(lines):
    section = _slice(lines, "Equity Profile", "Announcements")
    metrics = []

    if ")" in section:
        closing_index = section.index(")")
        if closing_index + 1 < len(section):
            metrics.append({"label": "Market Cap (000's)", "value": section[closing_index + 1]})

    if "Shares" in section:
        metrics.append({"label": "Shares", "value": _next_value(section, "Shares")})

    free_float_indexes = [index for index, value in enumerate(section) if value == "Free Float"]
    if free_float_indexes and free_float_indexes[0] + 1 < len(section):
        metrics.append({"label": "Free Float", "value": section[free_float_indexes[0] + 1]})
    if len(free_float_indexes) > 1 and free_float_indexes[1] + 1 < len(section):
        metrics.append({"label": "Free Float (%)", "value": section[free_float_indexes[1] + 1]})

    return metrics


def _is_period_token(line: str):
    return bool(re.match(r"^20\d{2}$", line) or re.match(r"^Q\d \d{4}$", line))


def _is_numeric_value(line: str) -> bool:
    cleaned = line.replace(",", "").replace(".", "").replace("-", "").replace("(", "").replace(")", "").strip()
    return cleaned.lstrip("0123456789").strip() == "" and bool(cleaned)


def _parse_period_block(block_lines):
    periods = []
    rows = []
    index = 0

    while index < len(block_lines) and _is_period_token(block_lines[index]):
        periods.append(block_lines[index])
        index += 1

    while index < len(block_lines):
        label = block_lines[index]
        index += 1

        # Skip lines that look like sub-headers (text, not numbers) before collecting values
        while index < len(block_lines) and not _is_numeric_value(block_lines[index]) and not _is_period_token(block_lines[index]):
            label = block_lines[index]
            index += 1

        values = []
        while index < len(block_lines) and len(values) < len(periods):
            if not periods or not _is_numeric_value(block_lines[index]):
                break
            values.append(block_lines[index])
            index += 1
        if label and values:
            rows.append({"label": label, "values": values})

    return {"periods": periods, "rows": rows}


def _parse_financial_blocks(lines):
    section = _slice(lines, "Financials", "Ratios")
    annual = {"periods": [], "rows": []}
    quarterly = {"periods": [], "rows": []}

    year_start = next((index for index, line in enumerate(section) if re.match(r"^20\d{2}$", line)), None)
    if year_start is not None:
        quarter_start = next(
            (index for index in range(year_start + 1, len(section)) if re.match(r"^Q\d \d{4}$", section[index])),
            None,
        )

        annual_end = quarter_start if quarter_start is not None else len(section)
        annual_block = section[year_start:annual_end]
        annual = _parse_period_block(annual_block)

        if quarter_start is not None:
            quarterly_end = next(
                (index for index in range(quarter_start + 1, len(section)) if section[index] == "Data powered by"),
                len(section),
            )
            quarterly_block = section[quarter_start:quarterly_end]
            quarterly = _parse_period_block(quarterly_block)

    return {
        "annual": annual,
        "quarterly": quarterly,
    }


def _parse_ratios(lines):
    section = _slice(lines, "Ratios", "Payouts")
    return _parse_period_block(section)


def _parse_announcements(lines):
    section = _slice(lines, "Announcements", "Financials")
    announcements = []
    pattern = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}$")

    for index, line in enumerate(section):
        if pattern.match(line):
            title = section[index + 1] if index + 1 < len(section) else ""
            announcements.append(
                {
                    "date": line,
                    "title": title.strip(),
                    "document_url": None,
                }
            )
        if len(announcements) == 5:
            break
    return announcements


def _build_price_chart(symbol, current_price, metrics):
    needed = {metric["label"]: metric["value"] for metric in metrics}
    labels = ["Open", "Low", "Current", "High", "LDCP"]
    values = [
        _to_float(needed.get("Open", "0")),
        _to_float(needed.get("Low", "0")),
        current_price,
        _to_float(needed.get("High", "0")),
        _to_float(needed.get("LDCP", "0")),
    ]
    return {"title": f"{symbol} price snapshot", "labels": labels, "values": values}


def _parse_timeseries(symbol: str, series_type: str):
    url = PSX_TIMESERIES_URL.format(series_type=series_type, symbol=_normalize_symbol(symbol))
    body = _fetch_html(url)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PSXServiceError("Official PSX timeseries data could not be parsed.") from exc

    rows = payload.get("data") or []
    points = []
    for row in rows:
        if not row or len(row) < 2:
            continue

        timestamp = int(row[0])
        close_price = float(row[1])
        volume = int(row[2]) if len(row) > 2 and row[2] is not None else None
        open_price = float(row[3]) if len(row) > 3 and row[3] is not None else None
        label_format = "%H:%M" if series_type == "int" else "%d %b %Y"
        label = datetime.fromtimestamp(timestamp).strftime(label_format)
        points.append(
            {
                "timestamp": timestamp,
                "label": label,
                "close": close_price,
                "open": open_price,
                "volume": volume,
            }
        )

    points.sort(key=lambda point: point["timestamp"])
    return points


def _build_historical_prices(symbol: str):
    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_intraday = executor.submit(_parse_timeseries, symbol, "int")
        fut_eod = executor.submit(_parse_timeseries, symbol, "eod")
        return {
            "intraday": fut_intraday.result(),
            "eod": fut_eod.result(),
            "default_range": "1M",
        }


def _parse_statement_table(url: str):
    cached = _statement_cache.get(url)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["value"]

    html = _fetch_html(url)
    tables = _parse_tables(html)
    if not tables:
        return {}

    table = tables[0]
    if not table or len(table) < 2:
        return {}

    headers = table[0]
    preferred_index = next((index for index, header in enumerate(headers) if index > 0 and header.startswith("FY ")), 1)
    rows = {}

    for row in table[1:]:
        if len(row) <= preferred_index:
            continue
        label = row[0].strip()
        if not label:
            continue

        chosen_value = row[preferred_index].strip()
        if chosen_value in {"", "-", "—"}:
            fallback_value = next((cell.strip() for cell in row[1:] if cell.strip() not in {"", "-", "—"}), None)
            chosen_value = fallback_value or chosen_value
        rows[label] = chosen_value

    _statement_cache[url] = {"timestamp": now, "value": rows}
    return rows


def _get_stockanalysis_fundamentals(symbol: str):
    normalized_symbol = _normalize_symbol(symbol)
    with ThreadPoolExecutor(max_workers=3) as executor:
        fut_income = executor.submit(_parse_statement_table, STOCK_ANALYSIS_INCOME_URL.format(symbol=normalized_symbol))
        fut_balance = executor.submit(_parse_statement_table, STOCK_ANALYSIS_BALANCE_URL.format(symbol=normalized_symbol))
        fut_cashflow = executor.submit(_parse_statement_table, STOCK_ANALYSIS_CASHFLOW_URL.format(symbol=normalized_symbol))
        income_rows = fut_income.result()
        balance_rows = fut_balance.result()
        cashflow_rows = fut_cashflow.result()

    return {
        "Revenue": income_rows.get("Revenue"),
        "Gross Profit": income_rows.get("Gross Profit"),
        "Operating Income": income_rows.get("Operating Income"),
        "Free Cash Flow": cashflow_rows.get("Free Cash Flow"),
        "EBITDA": income_rows.get("EBITDA"),
        "Assets": balance_rows.get("Total Assets"),
        "Liabilities": balance_rows.get("Total Liabilities"),
        "Equity": balance_rows.get("Total Equity") or balance_rows.get("Shareholders' Equity") or balance_rows.get("Total Common Equity"),
    }


def _get_stockanalysis_dividend_amounts(symbol: str):
    rows = _parse_statement_table(STOCK_ANALYSIS_DIVIDEND_URL.format(symbol=_normalize_symbol(symbol)))
    return rows


def _find_row_value(table, aliases: list[str]):
    for alias in aliases:
        alias_upper = alias.upper()
        for row in table.get("rows", []):
            if row["label"].upper() == alias_upper:
                value = next((cell for cell in row["values"] if cell not in {"", "-", "—"}), None)
                if value is not None:
                    return row["label"], value
    return None, None


def _build_fundamentals(symbol: str, annual_financials, quarterly_financials):
    annual_aliases = {
        "Revenue": ["Sales", "Revenue", "Net Sales", "Turnover", "Total Income", "Mark-up Earned"],
        "Gross Profit": ["Gross Profit", "Gross Profit / (Loss)"],
        "Operating Income": ["Operating Income", "Operating Profit", "Profit from Operations"],
        "Free Cash Flow": ["Free Cash Flow", "Free Cashflow"],
        "EBITDA": ["EBITDA"],
        "Assets": ["Total Assets", "Assets"],
        "Liabilities": ["Total Liabilities", "Liabilities"],
        "Equity": ["Equity", "Total Equity", "Shareholders' Equity"],
    }

    stockanalysis_values = {}
    try:
        stockanalysis_values = _get_stockanalysis_fundamentals(symbol)
    except Exception:
        stockanalysis_values = {}

    metrics = []
    for label, aliases in annual_aliases.items():
        source_label, value = _find_row_value(annual_financials, aliases)
        if value is None:
            source_label, value = _find_row_value(quarterly_financials, aliases)
        if value is None:
            value = stockanalysis_values.get(label)
            source_label = "Stock Analysis" if value else source_label

        display_value = value if value is not None else "N/A"
        if source_label and source_label not in {label, "Stock Analysis"}:
            metrics.append({"label": label, "value": f"{display_value} ({source_label})"})
        elif source_label == "Stock Analysis" and value is not None:
            metrics.append({"label": label, "value": f"{display_value} (Stock Analysis)"})
        else:
            metrics.append({"label": label, "value": display_value})

    return metrics


def _parse_dividend_history(symbol: str):
    normalized = _normalize_symbol(symbol)

    def _fetch_psx_payouts():
        return _post_form_html(PSX_PAYOUTS_URL, {"symbol": normalized})

    def _fetch_sa_dividends():
        try:
            html = _fetch_html(STOCK_ANALYSIS_DIVIDEND_URL.format(symbol=normalized))
            tables = _parse_tables(html)
            if tables:
                return [row[1].strip() for row in tables[0][1:] if len(row) >= 2]
        except Exception:
            pass
        return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_psx = executor.submit(_fetch_psx_payouts)
        fut_sa = executor.submit(_fetch_sa_dividends)
        html = fut_psx.result()
        stockanalysis_amounts = fut_sa.result()

    tables = _parse_tables(html)
    if not tables:
        return []

    history = []
    for index, row in enumerate(tables[0][1:7]):
        if len(row) < 4:
            continue
        history.append(
            {
                "date": row[0],
                "period": row[1],
                "details": row[2],
                "book_closure": row[3],
                "dividend_amount": stockanalysis_amounts[index] if index < len(stockanalysis_amounts) else None,
            }
        )
    return history


def _build_financial_chart(symbol, annual_financials):
    target_row = next((row for row in annual_financials["rows"] if row["label"] == "Sales"), None)
    if not target_row and annual_financials["rows"]:
        target_row = annual_financials["rows"][0]
    if not target_row:
        return {"title": f"{symbol} annual sales", "labels": [], "values": []}
    return {
        "title": f"{symbol} {target_row['label'].lower()}",
        "labels": annual_financials["periods"],
        "values": [_to_float(value) for value in target_row["values"]],
    }


def _build_ratio_chart(symbol, ratios):
    target_row = next((row for row in ratios["rows"] if "Net Profit Margin" in row["label"]), None)
    if not target_row and ratios["rows"]:
        target_row = ratios["rows"][0]
    if not target_row:
        return {"title": f"{symbol} net profit margin", "labels": [], "values": []}
    return {
        "title": f"{symbol} {target_row['label'].lower()}",
        "labels": ratios["periods"],
        "values": [_to_float(value) for value in target_row["values"]],
    }


def _normalize_symbol(symbol: str) -> str:
    return symbol.split()[0].strip().upper()


def _metric_value(metrics, label: str) -> str | None:
    for metric in metrics:
        if metric["label"] == label:
            return metric["value"]
    return None


def _equity_metric_value(metrics, prefix: str) -> str | None:
    normalized_prefix = prefix.lower()
    for metric in metrics:
        if metric["label"].lower().startswith(normalized_prefix):
            return metric["value"]
    return None


def _parse_company_snapshot(symbol: str):
    normalized_symbol = _normalize_symbol(symbol)
    cached = _snapshot_cache.get(normalized_symbol)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["snapshot"]

    html = _fetch_html(PSX_COMPANY_URL.format(symbol=normalized_symbol))
    lines = _visible_lines(html)

    if normalized_symbol not in lines:
        raise PSXServiceError("Official PSX company page could not be parsed.")

    pivot = lines.index(normalized_symbol)
    price_index = next((index for index in range(pivot, len(lines)) if lines[index].startswith("Rs.")), None)
    as_of_index = next((index for index in range(pivot, len(lines)) if lines[index].startswith("^ As of ")), None)

    if price_index is None or as_of_index is None or price_index < 2:
        raise PSXServiceError("Official PSX company page could not be parsed.")

    if lines[price_index - 2] in CORPORATE_ACTION_MARKERS and price_index >= 3:
        name = lines[price_index - 3]
        sector = lines[price_index - 1]
    else:
        name = lines[price_index - 2]
        sector = lines[price_index - 1]

    snapshot = {
        "normalized_symbol": normalized_symbol,
        "lines": lines,
        "name": name,
        "sector": sector,
        "current_price": _to_float(lines[price_index]),
        "absolute_change": _to_float(lines[price_index + 1]),
        "percent_change": _to_float(lines[price_index + 2]),
        "as_of": lines[as_of_index].replace("^ As of ", ""),
    }
    _snapshot_cache[normalized_symbol] = {"timestamp": now, "snapshot": snapshot}
    return snapshot


def _get_sector_company_map():
    cached = _sector_company_cache.get("sector_map")
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["value"]

    html = _fetch_html(PSX_SECTOR_SUMMARY_URL)
    pattern = re.compile(
        r'<div class="sectorSummary__companies__table" data-code="([^"]+)">.*?<h3>(.*?)</h3>.*?(<table.*?</table>)',
        re.S,
    )

    sector_map = {}
    for match in pattern.finditer(html):
        code = match.group(1).strip()
        sector_name = unescape(match.group(2)).strip().upper()
        tables = _parse_tables(match.group(3))
        if not tables:
            continue

        companies = []
        for row in tables[0][1:]:
            if row and row[0]:
                companies.append(
                    {
                        "symbol": _normalize_symbol(row[0]),
                        "name": row[1].strip() if len(row) > 1 else _normalize_symbol(row[0]),
                    }
                )

        if companies:
            sector_map[sector_name] = {"code": code, "companies": companies}

    if not sector_map:
        raise PSXServiceError("Official PSX sector data could not be parsed.")

    _sector_company_cache["sector_map"] = {"timestamp": now, "value": sector_map}
    return sector_map


def _parse_company_valuation(symbol: str):
    normalized_symbol = _normalize_symbol(symbol)
    cached = _company_valuation_cache.get(normalized_symbol)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["value"]

    snapshot = _parse_company_snapshot(normalized_symbol)
    quote_metrics = _parse_quote_metrics(snapshot["lines"])
    equity_profile = _parse_equity_profile(snapshot["lines"])

    pe = _safe_to_float(_metric_value(quote_metrics, "P/E Ratio (TTM)"))
    market_cap = _safe_to_float(_equity_metric_value(equity_profile, "Market Cap"))

    valuation = {
        "symbol": normalized_symbol,
        "name": snapshot["name"],
        "sector": snapshot["sector"].upper(),
        "pe": pe,
        "market_cap": market_cap,
    }
    _company_valuation_cache[normalized_symbol] = {"timestamp": now, "value": valuation}
    return valuation


def _get_sector_valuations(sector: str):
    normalized_sector = sector.upper()
    cached = _sector_valuation_cache.get(normalized_sector)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["value"]

    sector_map = _get_sector_company_map()
    sector_entry = sector_map.get(normalized_sector)
    if not sector_entry:
        return []

    companies = sector_entry["companies"]
    valuations = []
    max_workers = min(6, max(1, len(companies)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_parse_company_valuation, company["symbol"]): company["symbol"]
            for company in companies
        }
        for future in as_completed(future_map):
            try:
                valuation = future.result()
            except Exception:
                continue

            if valuation["sector"] == normalized_sector and valuation["pe"] and valuation["pe"] > 0:
                valuations.append(valuation)

    valuations.sort(key=lambda v: v["market_cap"] or 0, reverse=True)
    valuations = valuations[:8]
    _sector_valuation_cache[normalized_sector] = {"timestamp": now, "value": valuations}
    return valuations


def _compute_sector_average_pe(current_symbol: str, sector: str):
    normalized_symbol = _normalize_symbol(current_symbol)
    peer_valuations = [
        valuation
        for valuation in _get_sector_valuations(sector)
        if valuation["symbol"] != normalized_symbol
    ]

    if not peer_valuations:
        return None

    weighted_numerator = sum(
        valuation["market_cap"] * valuation["pe"]
        for valuation in peer_valuations
        if valuation["market_cap"] and valuation["market_cap"] > 0
    )
    weighted_denominator = sum(
        valuation["market_cap"]
        for valuation in peer_valuations
        if valuation["market_cap"] and valuation["market_cap"] > 0
    )

    if weighted_denominator > 0:
        return round(weighted_numerator / weighted_denominator, 2)

    pe_values = [valuation["pe"] for valuation in peer_valuations if valuation["pe"] and valuation["pe"] > 0]
    if not pe_values:
        return None
    return round(sum(pe_values) / len(pe_values), 2)


def _extract_latest_eps(annual_financials, quarterly_financials):
    for table in [annual_financials, quarterly_financials]:
        for row in table.get("rows", []):
            if "EPS" not in row["label"].upper():
                continue

            numeric_values = [_safe_to_float(v) for v in row["values"] if _safe_to_float(v) is not None]
            if not numeric_values:
                continue

            # If the most recent period looks like partial-year data (value is less than
            # 30% of the following period), skip it and use the next full-year figure.
            if len(numeric_values) >= 2:
                first, second = abs(numeric_values[0]), abs(numeric_values[1])
                if second > 0 and first / second < 0.3:
                    return round(numeric_values[1], 2)

            return round(numeric_values[0], 2)

    return None


def _compute_fair_price(valuation_eps: float | None, sector_average_pe: float | None):
    if valuation_eps is None or sector_average_pe is None or valuation_eps <= 0:
        return None

    return round(valuation_eps * sector_average_pe, 2)


def _compute_investment_signal(current_price, fair_price, quote_metrics, sector_average_pe):
    if fair_price is None or current_price is None or current_price <= 0:
        return None

    upside_pct = (fair_price - current_price) / current_price * 100

    own_pe = None
    for m in quote_metrics:
        if m["label"] == "P/E Ratio (TTM)":
            own_pe = _safe_to_float(m["value"])
            break

    reasons = []
    score = 0

    if upside_pct > 20:
        score += 3
        reasons.append(f"Trading {upside_pct:.1f}% below estimated fair value")
    elif upside_pct > 10:
        score += 2
        reasons.append(f"Trading {upside_pct:.1f}% below estimated fair value")
    elif upside_pct > 0:
        score += 1
        reasons.append(f"Slightly below estimated fair value ({upside_pct:.1f}%)")
    elif upside_pct > -10:
        score -= 1
        reasons.append(f"Trading {abs(upside_pct):.1f}% above estimated fair value")
    elif upside_pct > -20:
        score -= 2
        reasons.append(f"Trading {abs(upside_pct):.1f}% above estimated fair value")
    else:
        score -= 3
        reasons.append(f"Trading {abs(upside_pct):.1f}% above estimated fair value")

    if own_pe and own_pe > 0 and sector_average_pe and sector_average_pe > 0:
        pe_vs = (own_pe - sector_average_pe) / sector_average_pe * 100
        if pe_vs < -20:
            score += 2
            reasons.append(f"P/E ({own_pe:.1f}x) is {abs(pe_vs):.0f}% below sector average ({sector_average_pe:.1f}x)")
        elif pe_vs < 0:
            score += 1
            reasons.append(f"P/E ({own_pe:.1f}x) is below sector average ({sector_average_pe:.1f}x)")
        else:
            score -= 1
            reasons.append(f"P/E ({own_pe:.1f}x) is above sector average ({sector_average_pe:.1f}x)")

    if score >= 4:
        rating, color = "Strong Buy", "strong-buy"
        summary = "Appears significantly undervalued relative to sector peers"
    elif score >= 2:
        rating, color = "Buy", "buy"
        summary = "Appears undervalued relative to sector peers"
    elif score >= 0:
        rating, color = "Hold", "hold"
        summary = "Fairly valued relative to sector peers"
    elif score >= -2:
        rating, color = "Caution", "caution"
        summary = "Appears overvalued relative to sector peers"
    else:
        rating, color = "Avoid", "avoid"
        summary = "Appears significantly overvalued relative to sector peers"

    return {
        "rating": rating,
        "color": color,
        "summary": summary,
        "upside_percent": round(upside_pct, 2),
        "reasons": reasons,
    }


def _build_sector_pe_method(symbol: str, sector: str, peer_count: int):
    if peer_count == 0:
        return None

    normalized_symbol = _normalize_symbol(symbol)
    return (
        f"Market-cap weighted PSX peer P/E for {sector}, excluding {normalized_symbol}, "
        f"based on {peer_count} peer stocks."
    )


def _build_peer_company_names(symbol: str, sector: str):
    normalized_symbol = _normalize_symbol(symbol)
    peer_valuations = [
        valuation
        for valuation in _get_sector_valuations(sector)
        if valuation["symbol"] != normalized_symbol
    ]
    return [f"{valuation['symbol']} - {valuation['name']}" for valuation in sorted(peer_valuations, key=lambda item: item["name"])]


def get_stock_detail(symbol: str):
    snapshot = _parse_company_snapshot(symbol)
    lines = snapshot["lines"]
    current_price = snapshot["current_price"]
    quote_metrics = [{"label": "Current", "value": f"{current_price:.2f}"}] + _parse_quote_metrics(lines)

    profile_lines = _slice(lines, "Company Profile", "Equity Profile")
    business_description = profile_lines[2] if len(profile_lines) > 2 else ""
    address = _next_value(profile_lines, "ADDRESS")
    website = _next_value(profile_lines, "WEBSITE")
    registrar = _next_value(profile_lines, "REGISTRAR")
    auditor = _next_value(profile_lines, "AUDITOR")
    fiscal_year_end = _next_value(profile_lines, "Fiscal Year End")
    key_people = _parse_key_people(profile_lines)

    equity_profile = _parse_equity_profile(lines)
    announcements = _parse_announcements(lines)
    financial_blocks = _parse_financial_blocks(lines)
    ratios = _parse_ratios(lines)

    annual_financials = financial_blocks["annual"]
    quarterly_financials = financial_blocks["quarterly"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        fut_fundamentals = executor.submit(_build_fundamentals, symbol, annual_financials, quarterly_financials)
        fut_dividends = executor.submit(_parse_dividend_history, symbol)
        fut_sector = executor.submit(_get_sector_valuations, snapshot["sector"])
        fut_history = executor.submit(_build_historical_prices, symbol)

        fundamentals = fut_fundamentals.result()
        dividend_history = fut_dividends.result()
        sector_valuations = fut_sector.result()
        historical_prices = fut_history.result()

    sector_pe_peer_count = len([valuation for valuation in sector_valuations if valuation["symbol"] != _normalize_symbol(symbol)])
    sector_average_pe = _compute_sector_average_pe(symbol, snapshot["sector"])
    valuation_eps = _extract_latest_eps(annual_financials, quarterly_financials)
    fair_price = _compute_fair_price(valuation_eps, sector_average_pe)
    sector_pe_method = _build_sector_pe_method(symbol, snapshot["sector"], sector_pe_peer_count)
    peer_companies = _build_peer_company_names(symbol, snapshot["sector"])

    return {
        "symbol": symbol,
        "name": snapshot["name"],
        "sector": snapshot["sector"],
        "current_price": current_price,
        "absolute_change": snapshot["absolute_change"],
        "percent_change": snapshot["percent_change"],
        "as_of": snapshot["as_of"],
        "business_description": business_description,
        "address": address,
        "website": website,
        "registrar": registrar,
        "auditor": auditor,
        "fiscal_year_end": fiscal_year_end,
        "key_people": key_people,
        "quote_metrics": quote_metrics,
        "equity_profile": equity_profile,
        "fundamentals": fundamentals,
        "sector_average_pe": sector_average_pe,
        "sector_pe_peer_count": sector_pe_peer_count,
        "sector_pe_method": sector_pe_method,
        "peer_companies": peer_companies,
        "valuation_eps": valuation_eps,
        "fair_price": fair_price,
        "dividend_history": dividend_history,
        "announcements": announcements,
        "annual_financials": annual_financials,
        "quarterly_financials": quarterly_financials,
        "ratios": ratios,
        "price_chart": _build_price_chart(symbol, current_price, quote_metrics),
        "historical_prices": historical_prices,
        "financial_chart": _build_financial_chart(symbol, annual_financials),
        "ratio_chart": _build_ratio_chart(symbol, ratios),
    }
