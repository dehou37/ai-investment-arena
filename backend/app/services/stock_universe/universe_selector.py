
from typing import Any


TARGET_UNIVERSE_SIZE = 30
TARGET_SECTORS = ["Technology"]

# Curated broad-technology candidate pool.
# This includes semiconductors, software, cloud, hardware,
# cybersecurity, internet platforms and technology-enabled platforms.
TECH_CANDIDATE_SYMBOLS = {
    "AAPL", "NVDA", "MSFT",
    "GOOGL", "GOOG", "AMZN", "META",
    "TSM", "TSLA", "AVGO", "MU", "AMD",
    "ASML", "PLTR", "CSCO", "ORCL", "INTC",
    "AMAT", "PANW", "LRCX", "TXN", "SAP",
    "DELL", "NFLX", "CRWD", "BABA", "IBM",
    "ARM", "ANET", "KLAC", "ADI", "CRM",
    "MRVL", "QCOM", "SNDK", "STX", "UBER",
    "HPE", "ADBE", "INTU", "NOW", "SNOW",
    "NET", "FTNT", "CDNS", "SNPS", "DDOG",
    "APP", "LITE", "NXPI", "WDAY", "TEAM",
    "SHOP", "SPOT", "ADSK", "VEEV", "MDB",
    "ZS", "PANW", "MSTR", "HOOD", "PYPL",
}

# Companies that must appear in every completed snapshot.
MANDATORY_SYMBOLS = {"INTC", "AMZN", "META"}

# Alphabet has two publicly traded share classes.
# Prefer GOOGL, but accept GOOG if GOOGL is unavailable.
ALPHABET_SYMBOLS = {"GOOGL", "GOOG"}

PREFERRED_SYMBOLS = {
    "GOOG": "GOOGL",
}

# These are not ordinary publicly traded operating-company shares.
EXCLUDED_SYMBOLS = {
    "SPCX",
}

EXCLUDED_NAME_TERMS = (
    "warrant",
    "warrants",
    "right",
    "rights",
    "unit",
    "units",
    "preferred",
    "senior notes",
    "subordinated notes",
    "debenture",
    "bond",
    "etf",
    "exchange traded fund",
    "closed-end fund",
)

# Internal broad-technology industry labels.
# These are not official GICS classifications.
INDUSTRY_MAPPING = {
    "AAPL": "Consumer Technology",
    "NVDA": "Semiconductors",
    "MSFT": "Software & Cloud",
    "GOOGL": "Internet Platforms",
    "GOOG": "Internet Platforms",
    "AMZN": "E-commerce & Cloud",
    "META": "Internet Platforms",
    "TSM": "Semiconductors",
    "TSLA": "Technology-enabled Mobility",
    "AVGO": "Semiconductors & Infrastructure Software",
    "MU": "Semiconductors",
    "AMD": "Semiconductors",
    "ASML": "Semiconductor Equipment",
    "PLTR": "Software & AI",
    "CSCO": "Networking",
    "ORCL": "Software & Cloud",
    "INTC": "Semiconductors",
    "AMAT": "Semiconductor Equipment",
    "PANW": "Cybersecurity",
    "LRCX": "Semiconductor Equipment",
    "TXN": "Semiconductors",
    "SAP": "Enterprise Software",
    "DELL": "Computer Hardware",
    "NFLX": "Digital Media Platforms",
    "CRWD": "Cybersecurity",
    "BABA": "E-commerce & Cloud",
    "IBM": "IT Services & Software",
    "ARM": "Semiconductor IP",
    "ANET": "Networking",
    "KLAC": "Semiconductor Equipment",
    "ADI": "Semiconductors",
    "CRM": "Enterprise Software",
    "MRVL": "Semiconductors",
    "QCOM": "Semiconductors",
    "SNDK": "Data Storage",
    "STX": "Data Storage",
    "UBER": "Technology-enabled Platforms",
}


class UniverseSelectionError(Exception):
    """Raised when a valid 30-company universe cannot be selected."""


def parse_market_cap(value: Any) -> float:
    """
    Convert Nasdaq market-cap strings into numeric USD values.

    Examples:
        "$5.03T" -> 5030000000000
        "$349.18B" -> 349180000000
        "1234567890" -> 1234567890
    """
    if value is None:
        return 0.0

    text = str(value).strip().replace(",", "").replace("$", "")

    if not text or text.upper() in {"N/A", "NA", "NONE", "-"}:
        return 0.0

    multiplier = 1.0
    suffix = text[-1].upper()

    if suffix == "T":
        multiplier = 1_000_000_000_000
        text = text[:-1]
    elif suffix == "B":
        multiplier = 1_000_000_000
        text = text[:-1]
    elif suffix == "M":
        multiplier = 1_000_000
        text = text[:-1]
    elif suffix == "K":
        multiplier = 1_000
        text = text[:-1]

    try:
        return float(text.strip()) * multiplier
    except ValueError:
        return 0.0


def canonical_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    return PREFERRED_SYMBOLS.get(symbol, symbol)


def is_valid_exchange(row: dict[str, Any]) -> bool:
    exchange = str(
        row.get("exchange_source") or row.get("exchange") or ""
    ).strip().lower()

    return exchange in {"nasdaq", "nyse", "amex"}


def is_valid_company(row: dict[str, Any]) -> bool:
    symbol = str(row.get("symbol") or "").upper().strip()
    name = str(row.get("name") or "").strip()

    if not symbol or not name:
        return False

    if symbol in EXCLUDED_SYMBOLS:
        return False

    if symbol not in TECH_CANDIDATE_SYMBOLS:
        return False

    if any(term in name.lower() for term in EXCLUDED_NAME_TERMS):
        return False

    if not is_valid_exchange(row):
        return False

    return parse_market_cap(row.get("marketCap")) > 0


def select_top_companies(
    rows: list[dict[str, Any]],
    limit: int = TARGET_UNIVERSE_SIZE,
) -> list[dict[str, Any]]:
    """
    Select the highest-market-cap broad technology companies.

    Intel, Amazon, Meta and Alphabet are mandatory.
    Alphabet is represented by one share class only.
    """
    candidates: dict[str, dict[str, Any]] = {}

    for row in rows:
        if not is_valid_company(row):
            continue

        original_symbol = str(row["symbol"]).upper().strip()
        issuer_symbol = canonical_symbol(original_symbol)

        normalized = dict(row)
        normalized["symbol"] = original_symbol
        normalized["issuer_symbol"] = issuer_symbol
        normalized["market_cap"] = parse_market_cap(
            row.get("marketCap")
        )
        normalized["sector"] = "Technology"
        normalized["industry"] = INDUSTRY_MAPPING.get(
            original_symbol,
            "Technology"
        )

        existing = candidates.get(issuer_symbol)

        # Prefer GOOGL over GOOG when both share classes are available.
        if existing is None:
            candidates[issuer_symbol] = normalized
        elif original_symbol == issuer_symbol:
            candidates[issuer_symbol] = normalized

    if "GOOGL" not in candidates:
        if "GOOG" in candidates:
            candidates["GOOGL"] = candidates.pop("GOOG")
        else:
            raise UniverseSelectionError(
                "Alphabet (GOOGL or GOOG) was not found."
            )

    missing = MANDATORY_SYMBOLS - candidates.keys()

    if missing:
        raise UniverseSelectionError(
            f"Mandatory companies missing from screener: "
            f"{', '.join(sorted(missing))}"
        )

    ranked = sorted(
        candidates.values(),
        key=lambda item: item["market_cap"],
        reverse=True,
    )

    selected = ranked[:limit]
    selected_symbols = {item["issuer_symbol"] for item in selected}

    mandatory = MANDATORY_SYMBOLS | {"GOOGL"}

    for symbol in mandatory:
        if symbol not in selected_symbols:
            mandatory_company = candidates[symbol]

            selected[-1] = mandatory_company

            selected_symbols = {
                item["issuer_symbol"] for item in selected
            }

    selected.sort(
        key=lambda item: item["market_cap"],
        reverse=True,
    )

    if len(selected) != limit:
        raise UniverseSelectionError(
            f"Expected {limit} companies, selected {len(selected)}."
        )

    for rank, company in enumerate(selected, start=1):
        company["sector_rank"] = rank

    return selected
