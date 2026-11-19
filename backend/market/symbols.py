"""
market/symbols.py
=================
Finds NSE companies for Company Search and the watchlist.

A query (name, brand or NSE symbol) is resolved in this order:
  1. the watchlist (backend/data/watchlist.json) — tuned aliases & exclusions
  2. the company directory (backend/data/company_directory.json) — extra
     brand aliases such as "Paytm" for One97 Communications
  3. Yahoo Finance's symbol search, keeping NSE-listed equities only

The sector is taken from Yahoo's classification (mapped onto the watchlist's
sectors so sector peers can be used) or from the directory.
"""

import json
import logging
import re

import requests

from config import DIRECTORY_FILE, WATCHLIST_FILE

logger = logging.getLogger(__name__)

YAHOO_SEARCH_HOSTS = ["https://query2.finance.yahoo.com/v1/finance/search",
                      "https://query1.finance.yahoo.com/v1/finance/search"]
YAHOO_SEARCH = YAHOO_SEARCH_HOSTS[0]
_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) brand-risk-monitor"

# Directory sectors (report naming) → watchlist sectors
DIRECTORY_SECTORS = {
    "Banking & Finance": "Financial Services", "FinTech": "Financial Services", "NBFC": "Financial Services",
    "Insurance": "Financial Services", "IT Services": "IT Services", "Automotive": "Automobile",
    "FMCG": "FMCG", "Healthcare": "Healthcare", "Metals & Mining": "Metals & Mining",
    "Energy & Power": "Energy", "Conglomerate": "Energy", "Consumer Tech": "Consumer & Retail",
    "Retail": "Consumer & Retail", "EdTech": "Consumer & Retail", "Cement & Materials": "Infrastructure & Materials",
    "Infrastructure": "Infrastructure & Materials", "Engineering": "Infrastructure & Materials",
    "Telecom": "Telecom", "Aviation": "Transport & Logistics", "Media": "Media & Entertainment",
    "Real Estate": "Real Estate",
}

_SUFFIX = re.compile(r"\s*\b(limited|ltd\.?|the|corporation|corp\.?|company|co\.?)\b\.?\s*", re.I)


def yahoo_sector(sector: str | None, industry: str | None) -> str | None:
    """Map Yahoo's sector/industry onto the watchlist's sector names."""
    s, i = (sector or ""), (industry or "").lower()
    if not s:
        return None
    if s == "Financial Services":
        return "Financial Services"
    if s == "Technology":
        return "IT Services"
    if s == "Communication Services":
        return "Telecom" if "telecom" in i else "Media & Entertainment"
    if s == "Consumer Cyclical":
        return "Automobile" if "auto" in i else "Consumer & Retail"
    if s == "Consumer Defensive":
        return "FMCG"
    if s == "Healthcare":
        return "Healthcare"
    if s == "Basic Materials":
        if "building" in i or "cement" in i:
            return "Infrastructure & Materials"
        return "Chemicals" if "chemical" in i else "Metals & Mining"
    if s in ("Energy", "Utilities"):
        return "Energy"
    if s == "Industrials":
        if "defense" in i or "aerospace" in i:
            return "Defence"
        if any(k in i for k in ("airline", "airport", "marine", "freight", "railroad", "trucking", "logistics")):
            return "Transport & Logistics"
        if "construction" in i or "infrastructure" in i:
            return "Infrastructure & Materials"
        return "Capital Goods"
    if s == "Real Estate":
        return "Real Estate"
    return s


def load_watchlist() -> dict:
    return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))


def save_watchlist(wl: dict) -> None:
    WATCHLIST_FILE.write_text(json.dumps(wl, indent=1, ensure_ascii=False), encoding="utf-8")


def _directory() -> list[dict]:
    if DIRECTORY_FILE.exists():
        return json.loads(DIRECTORY_FILE.read_text(encoding="utf-8")).get("companies", [])
    return []


def core_name(name: str) -> str:
    return _SUFFIX.sub(" ", name or "").strip(" .,&") or name


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def directory_match(q: str) -> dict | None:
    nq = _norm(q)
    for d in _directory():
        if nq in {_norm(d["name"]), *(_norm(a) for a in d.get("aliases", []))}:
            return d
    return None


def _yahoo_quotes(q: str) -> list[dict]:
    """Yahoo's search sometimes answers 200 with no quotes; try the second host before giving up."""
    for url in YAHOO_SEARCH_HOSTS:
        try:
            r = _session.get(url, params={"q": q, "quotesCount": 15, "newsCount": 0, "listsCount": 0}, timeout=15)
            r.raise_for_status()
            quotes = r.json().get("quotes", [])
            if quotes:
                return quotes
        except Exception as exc:
            logger.warning("Yahoo symbol search failed for %r at %s: %s", q, url, exc)
    return []


def symbol_lookup(candidate: str) -> dict | None:
    """Treat the query as an NSE symbol and check it against the price API (search fallback)."""
    sym = re.sub(r"[^A-Z0-9&-]", "", (candidate or "").upper())
    if not sym or len(sym) > 20:
        return None
    try:
        from market.nse_prices import _download
        meta = _download(sym, retries=1).get("meta", {})
    except Exception:
        return None
    if meta.get("exchangeName") not in ("NSI", None) and "NSE" not in (meta.get("fullExchangeName") or ""):
        return None
    long_name = meta.get("longName") or meta.get("shortName") or sym
    return {"symbol": sym, "name": core_name(long_name), "legalName": long_name, "sector": None, "industry": None}


def yahoo_search(q: str, limit: int = 8) -> list[dict]:
    quotes = _yahoo_quotes(q)
    out = []
    for x in quotes:
        sym = x.get("symbol", "")
        if x.get("exchange") != "NSI" or x.get("quoteType") != "EQUITY" or not sym.endswith(".NS"):
            continue
        base = sym[:-3]
        if "-" in base and base.split("-")[-1] in ("BL", "BE", "SM", "RR", "IT"):   # block-deal / alt series
            continue
        out.append({"symbol": base, "name": core_name(x.get("longname") or x.get("shortname") or base),
                    "legalName": x.get("longname") or x.get("shortname"),
                    "sector": yahoo_sector(x.get("sector"), x.get("industry")), "industry": x.get("industry")})
    return out[:limit]


def make_profile(symbol: str, name: str, sector: str | None, aliases: list[str] | None = None) -> dict:
    """A watchlist-style profile for a company found by search."""
    names = [name] + [a for a in (aliases or []) if a and a.lower() != name.lower()]
    if symbol.isalpha() and len(symbol) >= 3 and symbol.upper() not in {n.upper() for n in names}:
        names.append(symbol.upper())
    query = " OR ".join(f'"{n}"' if " " in n else n for n in names[:4])
    return {"symbol": symbol, "name": name, "sector": sector or "Other", "query": query,
            "aliases": names, "exclude": []}


def suggest(q: str, limit: int = 8) -> list[dict]:
    """Suggestions for the search box: watchlist hits first, then Yahoo (NSE only)."""
    q = (q or "").strip()
    if not q:
        return []
    nq = _norm(q)
    wl = load_watchlist()["companies"]
    out, seen = [], set()
    for c in wl:
        if nq in _norm(c["name"]) or nq in _norm(c["symbol"]) or any(nq in _norm(a) for a in c.get("aliases", [])):
            out.append({"symbol": c["symbol"], "name": c["name"], "sector": c["sector"], "onWatchlist": True})
            seen.add(c["symbol"])
    if len(out) < limit:
        d = directory_match(q)
        hits = yahoo_search(d["name"] if d else q, limit)
        if not hits and not out:
            hit = symbol_lookup(q) or (symbol_lookup(d["name"]) if d else None)
            hits = [hit] if hit else []
        for y in hits:
            if y["symbol"] not in seen:
                out.append({**y, "onWatchlist": False})
                seen.add(y["symbol"])
    return out[:limit]


def resolve(q: str) -> dict | None:
    """Best profile for a query, or None if it is not an NSE-listed company."""
    q = (q or "").strip()
    if not q:
        return None
    nq = _norm(q)
    for c in load_watchlist()["companies"]:
        if nq in {_norm(c["symbol"]), _norm(c["name"])} or nq in {_norm(a) for a in c.get("aliases", [])}:
            return {**c, "onWatchlist": True}
    d = directory_match(q)
    hits = yahoo_search(d["name"] if d else q, 5)
    if not hits:                                    # search flaked or found nothing: try it as a symbol
        hit = symbol_lookup(q) or (symbol_lookup(d["name"]) if d else None)
        hits = [hit] if hit else []
    exact = [h for h in hits if _norm(h["symbol"]) == nq]
    if not (exact or hits):
        return None
    h = (exact or hits)[0]
    # a curated directory entry wins: it knows e.g. that Paytm is FinTech (Yahoo says Technology)
    sector = (DIRECTORY_SECTORS.get(d["sector"]) if d else None) or h["sector"]
    name = d["name"] if d else h["name"]
    aliases = (d.get("aliases", []) if d else []) + ([h["name"]] if d and core_name(h["name"]) != d["name"] else [])
    return {**make_profile(h["symbol"], name, sector, aliases), "legalName": h["legalName"], "onWatchlist": False}
