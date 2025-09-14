
import requests
from typing import Tuple

class ProviderError(Exception):
    pass

def fetch_price_yahoo(ticker: str) -> Tuple[float, str]:
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200: raise ProviderError(f"yahoo http {r.status_code}")
    j = r.json()
    q = (j.get("quoteResponse", {}).get("result") or [None])[0]
    if not q: raise ProviderError("yahoo: no result")
    price = q.get("regularMarketPrice") or q.get("postMarketPrice") or q.get("preMarketPrice")
    if price is None: raise ProviderError("yahoo: no price field")
    return float(price), "yahoo"

def fetch_price_stooq(ticker: str) -> Tuple[float, str]:
    import csv, io
    def try_sym(sym):
        url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, timeout=10)
        if r.status_code != 200: raise ProviderError(f"stooq http {r.status_code}")
        text = r.text.strip()
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if len(rows) < 2: raise ProviderError("stooq: no row")
        close = rows[1][6]
        val = float(close)
        return val, "stooq"
    try:
        return try_sym(ticker.lower())
    except Exception:
        return try_sym((ticker + ".us").lower())

def fetch_price_alpha(ticker: str, key: str) -> Tuple[float, str]:
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={key or 'demo'}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200: raise ProviderError(f"alphavantage http {r.status_code}")
    j = r.json()
    q = j.get("Global Quote") or j.get("globalQuote")
    if not q: raise ProviderError(j.get("Note","alphavantage: no quote"))
    price = q.get("05. price") or q.get("05. Price")
    return float(price), "alphavantage"

def fetch_price_for(ticker: str, provider: str, key: str = "") -> Tuple[float, str]:
    if provider == "yahoo": return fetch_price_yahoo(ticker)
    if provider == "stooq": return fetch_price_stooq(ticker)
    if provider == "alphavantage": return fetch_price_alpha(ticker, key)
    raise ProviderError("unknown provider")
