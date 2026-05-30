"""
extractor.py — NLP extraction engine
Parses unstructured article text into structured FundingRound fields.
Pure regex + lookup dictionaries. No LLM needed.
"""

import re
import hashlib
from typing import Optional, List, Tuple

# ── Amount parsing ────────────────────────────────────────────────────────────

_MULTIPLIERS = {
    "k": 1_000, "K": 1_000, "thousand": 1_000,
    "m": 1_000_000, "M": 1_000_000, "mn": 1_000_000, "mil": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000, "B": 1_000_000_000, "bn": 1_000_000_000,
    "billion": 1_000_000_000,
    "cr": 10_000_000 / 83, "crore": 10_000_000 / 83,
    "lakh": 100_000 / 83,
}

_AMOUNT_PATTERNS = [
    re.compile(r"\$\s*([\d,.]+)\s*(thousand|million|billion|[kKmMbB](?:n|il)?)\b", re.I),
    re.compile(r"([\d,.]+)\s*(thousand|million|billion)\s*(?:dollars?|USD|usd)", re.I),
    re.compile(r"(?:₹|Rs\.?\s*)([\d,.]+)\s*(crore|lakh|cr)\b", re.I),
    re.compile(r"USD\s*([\d,.]+)\s*(thousand|million|billion|[mMbBkK])\b", re.I),
]


def parse_amount(text: str) -> Optional[float]:
    for pattern in _AMOUNT_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                num = float(m.group(1).replace(",", ""))
                suffix = m.group(2) if len(m.groups()) > 1 else ""
                if suffix:
                    mult = _MULTIPLIERS.get(suffix, _MULTIPLIERS.get(suffix.lower(), 1))
                    num *= mult
                if 10_000 <= num <= 200_000_000_000:
                    return round(num, 2)
            except (ValueError, IndexError):
                continue
    return None


def format_amount(usd: float) -> str:
    if usd >= 1_000_000_000:
        return f"${usd / 1_000_000_000:.1f}B"
    elif usd >= 1_000_000:
        return f"${usd / 1_000_000:.1f}M"
    elif usd >= 1_000:
        return f"${usd / 1_000:.0f}K"
    return f"${usd:.0f}"


# ── Round type ────────────────────────────────────────────────────────────────

_ROUND_PATTERNS: List[Tuple[re.Pattern, Optional[str]]] = [
    (re.compile(r"\bpre[- ]?seed\b", re.I), "pre-seed"),
    (re.compile(r"\bseed\b(?!\s+(?:stage|company|round))", re.I), "seed"),
    (re.compile(r"\bseries\s+([A-F])\b", re.I), None),
    (re.compile(r"\bpre[- ]?series\s+[A-F]\b", re.I), "pre-series"),
    (re.compile(r"\bbridge\s+(?:round|funding|loan)?\b", re.I), "bridge"),
    (re.compile(r"\bIPO\b"), "IPO"),
    (re.compile(r"\bacquisition\b", re.I), "acquisition"),
    (re.compile(r"\bdebt\s+(?:financing|round|funding)\b", re.I), "debt"),
    (re.compile(r"\bgrowth\s+(?:equity|round|funding)\b", re.I), "growth"),
    (re.compile(r"\b(?:angel|pre-angel)\b(?!\s+(?:falls?|number))", re.I), "angel"),
    (re.compile(r"\bgrant\b", re.I), "grant"),
]

_STAGE_MAP = {
    "pre-seed": "early", "seed": "early", "angel": "early", "pre-series": "early",
    "Series A": "early", "Series B": "growth", "Series C": "growth",
    "bridge": "growth", "growth": "growth",
    "Series D": "late", "Series E": "late", "Series F": "late",
    "IPO": "late", "debt": "late",
    "acquisition": "late", "grant": "early",
}


def parse_round_type(text: str) -> str:
    for pattern, round_name in _ROUND_PATTERNS:
        m = pattern.search(text)
        if m:
            if round_name is None:
                return f"Series {m.group(1).upper()}"
            return round_name
    return "unknown"


def get_stage(round_type: str) -> str:
    return _STAGE_MAP.get(round_type, "unknown")


# ── Investors ─────────────────────────────────────────────────────────────────

_INVESTOR_PATTERNS = [
    re.compile(r"led by\s+(.+?)(?:\.|,\s*(?:with|and\s+participation)|$)", re.I),
    re.compile(r"backed by\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"investors?\s+(?:include|including)\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"participation\s+(?:from|of)\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"co-led by\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"from\s+(.+?)\s+(?:led|with|and)\s+", re.I),
]

_NOISE_WORDS = {
    "others", "more", "several", "various", "existing", "previous",
    "new", "strategic", "undisclosed",
}


def parse_investors(text: str) -> List[str]:
    for pattern in _INVESTOR_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            parts = re.split(r",\s*|\s+and\s+", raw)
            investors = []
            for part in parts:
                name = part.strip().rstrip(".")
                if name and len(name) > 2 and name.lower() not in _NOISE_WORDS:
                    investors.append(name[:80])
            if investors:
                return investors[:6]
    return []


# ── Geography ─────────────────────────────────────────────────────────────────

_CITY_MAP = {
    "bangalore": ("India", "South Asia"),
    "bengaluru": ("India", "South Asia"),
    "mumbai": ("India", "South Asia"),
    "delhi": ("India", "South Asia"),
    "new delhi": ("India", "South Asia"),
    "hyderabad": ("India", "South Asia"),
    "pune": ("India", "South Asia"),
    "chennai": ("India", "South Asia"),
    "kolkata": ("India", "South Asia"),
    "gurgaon": ("India", "South Asia"),
    "gurugram": ("India", "South Asia"),
    "noida": ("India", "South Asia"),
    "jaipur": ("India", "South Asia"),
    "ahmedabad": ("India", "South Asia"),
    "surat": ("India", "South Asia"),
    "singapore": ("Singapore", "Southeast Asia"),
    "jakarta": ("Indonesia", "Southeast Asia"),
    "kuala lumpur": ("Malaysia", "Southeast Asia"),
    "bangkok": ("Thailand", "Southeast Asia"),
    "manila": ("Philippines", "Southeast Asia"),
    "ho chi minh": ("Vietnam", "Southeast Asia"),
    "hanoi": ("Vietnam", "Southeast Asia"),
    "san francisco": ("USA", "North America"),
    "palo alto": ("USA", "North America"),
    "menlo park": ("USA", "North America"),
    "new york": ("USA", "North America"),
    "new york city": ("USA", "North America"),
    "nyc": ("USA", "North America"),
    "boston": ("USA", "North America"),
    "seattle": ("USA", "North America"),
    "los angeles": ("USA", "North America"),
    "austin": ("USA", "North America"),
    "chicago": ("USA", "North America"),
    "miami": ("USA", "North America"),
    "london": ("UK", "Europe"),
    "berlin": ("Germany", "Europe"),
    "paris": ("France", "Europe"),
    "amsterdam": ("Netherlands", "Europe"),
    "stockholm": ("Sweden", "Europe"),
    "helsinki": ("Finland", "Europe"),
    "zurich": ("Switzerland", "Europe"),
    "barcelona": ("Spain", "Europe"),
    "madrid": ("Spain", "Europe"),
    "lisbon": ("Portugal", "Europe"),
    "dublin": ("Ireland", "Europe"),
    "munich": ("Germany", "Europe"),
    "copenhagen": ("Denmark", "Europe"),
    "oslo": ("Norway", "Europe"),
    "warsaw": ("Poland", "Europe"),
    "prague": ("Czech Republic", "Europe"),
    "toronto": ("Canada", "North America"),
    "vancouver": ("Canada", "North America"),
    "montreal": ("Canada", "North America"),
    "sydney": ("Australia", "Oceania"),
    "melbourne": ("Australia", "Oceania"),
    "tel aviv": ("Israel", "Middle East"),
    "dubai": ("UAE", "Middle East"),
    "riyadh": ("Saudi Arabia", "Middle East"),
    "abu dhabi": ("UAE", "Middle East"),
    "nairobi": ("Kenya", "Africa"),
    "lagos": ("Nigeria", "Africa"),
    "cairo": ("Egypt", "Africa"),
    "johannesburg": ("South Africa", "Africa"),
    "cape town": ("South Africa", "Africa"),
    "tokyo": ("Japan", "East Asia"),
    "seoul": ("South Korea", "East Asia"),
    "beijing": ("China", "East Asia"),
    "shanghai": ("China", "East Asia"),
    "shenzhen": ("China", "East Asia"),
    "hong kong": ("Hong Kong", "East Asia"),
    "taipei": ("Taiwan", "East Asia"),
    "dhaka": ("Bangladesh", "South Asia"),
    "karachi": ("Pakistan", "South Asia"),
    "lahore": ("Pakistan", "South Asia"),
    "colombo": ("Sri Lanka", "South Asia"),
    "kathmandu": ("Nepal", "South Asia"),
    "sao paulo": ("Brazil", "Latin America"),
    "mexico city": ("Mexico", "Latin America"),
    "buenos aires": ("Argentina", "Latin America"),
    "bogota": ("Colombia", "Latin America"),
    "lima": ("Peru", "Latin America"),
    "santiago": ("Chile", "Latin America"),
}

_COUNTRY_PATTERNS = [
    (re.compile(r"\b(india(?:n)?)\b", re.I), ("India", "South Asia")),
    (re.compile(r"\b(usa|u\.s\.|united states|american)\b", re.I), ("USA", "North America")),
    (re.compile(r"\b(uk|united kingdom|british)\b", re.I), ("UK", "Europe")),
    (re.compile(r"\b(singapore(?:an)?)\b", re.I), ("Singapore", "Southeast Asia")),
    (re.compile(r"\b(germany|german)\b", re.I), ("Germany", "Europe")),
    (re.compile(r"\b(france|french)\b", re.I), ("France", "Europe")),
    (re.compile(r"\b(canada|canadian)\b", re.I), ("Canada", "North America")),
    (re.compile(r"\b(australia(?:n)?)\b", re.I), ("Australia", "Oceania")),
    (re.compile(r"\b(israel|israeli)\b", re.I), ("Israel", "Middle East")),
    (re.compile(r"\b(nigeria(?:n)?)\b", re.I), ("Nigeria", "Africa")),
    (re.compile(r"\b(kenya(?:n)?)\b", re.I), ("Kenya", "Africa")),
    (re.compile(r"\b(brazil(?:ian)?)\b", re.I), ("Brazil", "Latin America")),
    (re.compile(r"\b(indonesia(?:n)?)\b", re.I), ("Indonesia", "Southeast Asia")),
    (re.compile(r"\b(sweden|swedish)\b", re.I), ("Sweden", "Europe")),
    (re.compile(r"\b(netherlands|dutch)\b", re.I), ("Netherlands", "Europe")),
    (re.compile(r"\b(china|chinese)\b", re.I), ("China", "East Asia")),
    (re.compile(r"\b(japan(?:ese)?)\b", re.I), ("Japan", "East Asia")),
    (re.compile(r"\b(south korea|korean)\b", re.I), ("South Korea", "East Asia")),
    (re.compile(r"\b(uae|emirates)\b", re.I), ("UAE", "Middle East")),
    (re.compile(r"\b(pakistan(?:i)?)\b", re.I), ("Pakistan", "South Asia")),
    (re.compile(r"\b(bangladesh(?:i)?)\b", re.I), ("Bangladesh", "South Asia")),
    (re.compile(r"\b(egypt(?:ian)?)\b", re.I), ("Egypt", "Africa")),
    (re.compile(r"\b(mexico|mexican)\b", re.I), ("Mexico", "Latin America")),
    (re.compile(r"\b(colombia(?:n)?)\b", re.I), ("Colombia", "Latin America")),
    (re.compile(r"\b(thailand|thai)\b", re.I), ("Thailand", "Southeast Asia")),
    (re.compile(r"\b(vietnam(?:ese)?)\b", re.I), ("Vietnam", "Southeast Asia")),
    (re.compile(r"\b(philippines|filipino)\b", re.I), ("Philippines", "Southeast Asia")),
]


def parse_geography(text: str):
    text_lower = text.lower()
    for city, (country, region) in _CITY_MAP.items():
        if re.search(r'\b' + re.escape(city) + r'\b', text_lower):
            return country, city.title(), region
    for pattern, (country, region) in _COUNTRY_PATTERNS:
        if pattern.search(text):
            return country, None, region
    return None, None, None


# ── Sector classification ─────────────────────────────────────────────────────

_SECTOR_TAXONOMY = {
    "AI/ML": {
        "keywords": ["artificial intelligence", "machine learning", "llm", "generative ai",
                     "large language model", "deep learning", "neural network", "nlp",
                     "computer vision", "ai model", "foundation model", "openai", "gpt",
                     "autonomous", "inference", "training", "fine-tuning", "rag",
                     "agentic", "ai agent", "copilot"],
        "sub_sectors": {
            "LLM / Foundation Models": ["llm", "large language model", "foundation model", "gpt", "claude", "gemini"],
            "AI Infrastructure": ["inference", "training infrastructure", "gpu cloud", "mlops"],
            "Computer Vision": ["computer vision", "image recognition", "video ai"],
            "AI Agents": ["ai agent", "agentic", "autonomous agent", "copilot"],
        }
    },
    "Fintech": {
        "keywords": ["payments", "banking", "insurance", "lending", "credit", "neobank",
                     "insurtech", "wealthtech", "defi", "blockchain", "crypto", "nft",
                     "financial services", "fintech", "regtech", "paytech", "embedded finance",
                     "buy now pay later", "bnpl", "remittance", "forex"],
        "sub_sectors": {
            "Payments": ["payments", "payment processing", "merchant", "pos"],
            "Crypto / DeFi": ["defi", "blockchain", "crypto", "web3", "nft", "dao"],
            "Insurtech": ["insurance", "insurtech"],
            "Lending / Credit": ["lending", "credit", "bnpl", "loan", "mortgage"],
            "Neobank": ["neobank", "challenger bank", "digital bank"],
        }
    },
    "Healthtech": {
        "keywords": ["health", "medical", "pharma", "biotech", "therapeutics", "diagnostics",
                     "telemedicine", "telehealth", "mental health", "drug discovery",
                     "clinical", "genomics", "digital health", "medtech"],
        "sub_sectors": {
            "Biotech / Pharma": ["biotech", "pharma", "therapeutics", "drug discovery", "genomics"],
            "Digital Health": ["digital health", "telemedicine", "telehealth", "remote care"],
            "Mental Health": ["mental health", "therapy", "wellness", "behavioral health"],
            "Medical Devices": ["medtech", "medical device", "diagnostics", "wearable health"],
        }
    },
    "SaaS": {
        "keywords": ["software as a service", "saas", "b2b software", "enterprise software",
                     "crm", "erp", "hrtech", "hr tech", "productivity", "workflow",
                     "no-code", "low-code", "api", "developer tools", "devtools"],
        "sub_sectors": {
            "HR Tech": ["hrtech", "hr tech", "human resources", "payroll", "recruitment"],
            "Developer Tools": ["devtools", "developer tools", "api", "sdk", "ci/cd"],
            "No-Code / Low-Code": ["no-code", "low-code", "nocode"],
            "CRM / Sales": ["crm", "sales automation", "revenue operations"],
        }
    },
    "Edtech": {
        "keywords": ["education", "learning", "edtech", "e-learning", "online course",
                     "upskilling", "tutoring", "lms", "skills", "bootcamp", "university"],
        "sub_sectors": {}
    },
    "Logistics / Supply Chain": {
        "keywords": ["logistics", "supply chain", "delivery", "shipping", "freight",
                     "warehouse", "last mile", "fleet management", "trucking"],
        "sub_sectors": {}
    },
    "Climate / Cleantech": {
        "keywords": ["climate", "clean energy", "renewable", "solar", "ev", "electric vehicle",
                     "carbon", "sustainability", "greentech", "cleantech", "net zero",
                     "battery", "hydrogen", "wind energy"],
        "sub_sectors": {
            "EV / Mobility": ["ev", "electric vehicle", "e-mobility", "charging"],
            "Solar / Wind": ["solar", "wind", "renewable energy"],
            "Carbon": ["carbon capture", "carbon offset", "net zero"],
        }
    },
    "E-commerce / Retail": {
        "keywords": ["e-commerce", "ecommerce", "retail", "marketplace", "d2c",
                     "direct to consumer", "shopping", "fashion", "beauty", "fmcg"],
        "sub_sectors": {}
    },
    "Real Estate / Proptech": {
        "keywords": ["real estate", "proptech", "property", "housing", "mortgage",
                     "co-working", "coworking", "construction tech"],
        "sub_sectors": {}
    },
    "Foodtech / Agritech": {
        "keywords": ["food", "restaurant", "agritech", "agriculture", "foodtech",
                     "alternative protein", "plant-based", "agri", "farm"],
        "sub_sectors": {}
    },
    "Cybersecurity": {
        "keywords": ["cybersecurity", "security", "privacy", "data protection", "threat",
                     "zero trust", "soc", "endpoint security", "identity"],
        "sub_sectors": {}
    },
    "Space / Defense": {
        "keywords": ["space", "satellite", "defense", "aerospace", "drone", "rocket"],
        "sub_sectors": {}
    },
    "Gaming / Entertainment": {
        "keywords": ["gaming", "game", "esports", "entertainment", "media", "streaming",
                     "content", "creator economy", "metaverse"],
        "sub_sectors": {}
    },
}


def classify_sector(text: str) -> Tuple[Optional[str], Optional[str]]:
    text_lower = text.lower()
    best_sector = None
    best_sub = None
    best_count = 0

    for sector, data in _SECTOR_TAXONOMY.items():
        count = sum(1 for kw in data["keywords"] if kw in text_lower)
        if count > best_count:
            best_count = count
            best_sector = sector
            best_sub = None
            best_sub_count = 0
            for sub, sub_kws in data.get("sub_sectors", {}).items():
                sc = sum(1 for kw in sub_kws if kw in text_lower)
                if sc > best_sub_count:
                    best_sub_count = sc
                    best_sub = sub

    return (best_sector if best_count >= 1 else None), best_sub


# ── Company extraction ────────────────────────────────────────────────────────

_COMPANY_RAISES_PATTERNS = [
    # "Acme AI raises $5M" / "Acme raises Series A"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+(?:raises?|secures?|closes?|gets?|bags?|receives?|lands?|nets?|wins?)\s+(?:\$|USD|Rs\.?|INR|EUR|£)", re.I),
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+(?:raises?|secures?|closes?)\s+(?:pre-seed|seed|series\s+[a-f]|angel|bridge|growth)", re.I),
    # "Acme completes $5M" / "Acme announces $5M"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+completes?\s+(?:\$|USD|a\s+\$)", re.I),
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+announces?\s+(?:a\s+)?(?:\$|USD|\d)", re.I),
    # "With a $55M round, Pomelo..."
    re.compile(r"^with\s+(?:a\s+)?\$[\d,.]+\s*[MBKmkb]*\s+(?:funding\s+)?round,?\s+(.+?)\s+(?:is|has|plans|aims|launches|expands|commits)", re.I),
    # "startup Yodawy banks $10m" / "Egyptian e-health startup Yodawy banks $10m"
    re.compile(r"(?:startup|company|firm|fintech|healthtech|edtech|saas)\s+(\w[\w\s.]{1,40}?)\s+(?:banks?|raises?|secures?|gets?|lands?)\s+\$", re.I),
    # "Exclusive: Sequoia backs Acme in $5M"
    re.compile(r"(?:exclusive|breaking|report)\s*:\s*.+?\s+backs?\s+(.+?)\s+(?:in|with)\s+\$", re.I),
    # "Sequoia backs Acme in $5M"
    re.compile(r"(?:[\w\s]+?)\s+backs?\s+(.+?)\s+(?:in|with)\s+\$", re.I),
    # "YC alum Lucis in $20M Series A"
    re.compile(r"(?:yc[- ]backed|y\s*combinator\s+alum|yc\s+alum)\s+(.+?)\s+(?:raises?|in|secures?|closes?)\s+\$", re.I),
    # "chip startup just raised $Y" (headline has company in first word before 'just')
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+just\s+(?:raised?|secured?|closed?)\s+\$", re.I),
    # "$5M raised by / for Acme"
    re.compile(r"(?:\$[\d,.]+\s*[MBKmkb]+|USD\s*[\d,.]+)\s+(?:raised|secured|invested)\s+(?:by|in|for)\s+(.+?)(?:\s*[-–,|]|$)", re.I),
    re.compile(r"(?:\$[\d,.]+\s*[MBKmkb]+|USD\s*[\d,.]+)\s+(?:for|to)\s+(.+?)(?:\s*[-–,|]|$)", re.I),
    # "Acme bags funding" / "Acme gets investment"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+(?:bags?|gets?|receives?|lands?|nets?|wins?)\s+(?:funding|investment|capital|backing)", re.I),
    # "Acme backed by Sequoia"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+backed\s+by\s+", re.I),
    # "Funding: Acme raises..."
    re.compile(r"^(?:funding|investment|seed|series\s+[a-f]|round|startup)\s*:\s*(.+?)\s+(?:raises?|secures?|closes?|gets?|bags?)", re.I),
    # "Acme, a [desc], raises..."
    re.compile(r"^(.+?),\s+a\s+.+?,\s+(?:raises?|secures?|closes?)", re.I),
    # "Acme acquired by BigCo"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+(?:gets?\s+acquired|acquired)\s+by\s+", re.I),
    re.compile(r"acquisition\s+of\s+(.+?)(?:\s+by|\s+for|\s*,|$)", re.I),
    # "Acme files for IPO"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+(?:files?\s+for\s+|plans?\s+|announces?\s+)?IPO\b", re.I),
    # "Acme launches X and raises $Y"
    re.compile(r"^(?:\[.+?\]\s*)?(.+?)\s+launches?\s+.{0,40}(?:and\s+)?(?:raises?|secures?|announces?)\s+\$", re.I),
]

_BAD_COMPANY_NAMES = {
    "unknown", "funding", "startup", "company", "firm", "the startup",
    "a startup", "a company", "new startup", "tech startup", "fintech",
    "india", "europe", "asia", "africa", "us", "uk", "this", "it",
    "the", "a", "an", "exclusive", "breaking",
}


def parse_company(text: str, description: str = "") -> str:
    """Extract company name from headline, with fallback to description."""
    sources_to_try = [text.strip()]
    if description:
        first_sentence = re.split(r'[.!?]', description)[0].strip()
        if first_sentence:
            sources_to_try.append(first_sentence)

    for src in sources_to_try:
        for pattern in _COMPANY_RAISES_PATTERNS:
            m = pattern.search(src)
            if m:
                name = m.group(1).strip()
                name = re.sub(r"^\[.+?\]\s*", "", name)
                name = name.rstrip(".,;:-–")
                name = re.sub(r"\s*\(.+?\)$", "", name)
                name = re.sub(r"^(?:a|an|the)\s+", "", name, flags=re.I)
                name = name.strip()
                if (name
                        and 1 < len(name) < 80
                        and name.lower() not in _BAD_COMPANY_NAMES
                        and not name.lower().startswith("http")):
                    return name

    return "Unknown"


# ── Domain extraction ─────────────────────────────────────────────────────────

_DOMAIN_PATTERN = re.compile(
    r'\b(?:https?://)?(?:www\.)?([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'\.(?:com|io|ai|co|tech|app|dev|net|org))\b', re.I
)

# News/aggregator domains that should never appear as a startup's own domain
_NEWS_DOMAINS = {
    "techcrunch.com", "google.com", "news.google.com", "forbes.com",
    "businessinsider.com", "sifted.eu", "venturebeat.com", "yourstory.com",
    "inc42.com", "e27.co", "techinasia.com", "disrupt-africa.com",
    "contxto.com", "news.ycombinator.com", "crunchbase.com", "crunchbase.news",
    "theinformation.com", "reuters.com", "bloomberg.com", "wsj.com",
    "ft.com", "economist.com", "wired.com", "mashable.com", "engadget.com",
    "the-ken.com", "entrackr.com", "restofworld.org", "axios.com",
    "feedburner.com", "feeds.feedburner.com", "rss.com", "feedproxy.google.com",
    "news.google.com", "yahoo.com", "apnews.com", "bbc.com", "cnbc.com",
    "indianexpress.com", "livemint.com", "economictimes.com", "moneycontrol.com",
    "hindustantimes.com", "ndtv.com", "scroll.in", "medianama.com",
}


def parse_domain(description: str, headline: str = "") -> Optional[str]:
    """Extract the startup's own domain from description text only (not the article URL)."""
    # Only scan description + headline text, never the article source URL
    for src in [description, headline]:
        if not src:
            continue
        for m in _DOMAIN_PATTERN.finditer(src):
            domain = m.group(1).lower()
            # Skip any known news/aggregator domain
            if not any(domain == nd or domain.endswith('.' + nd) for nd in _NEWS_DOMAINS):
                return domain
    return None


# ── Founder extraction ────────────────────────────────────────────────────────

_FOUNDER_PATTERNS = [
    # "founded by Jane Doe" / "co-founded by Jane Doe and John Smith"
    re.compile(r"(?:co-?founded?|founded?)\s+by\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})", re.I),
    # "CEO Jane Doe" / "CEO and co-founder Jane Doe"
    re.compile(r"\bCEO(?:\s+and\s+co-?founder)?\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})"),
    # "Jane Doe, CEO" / "Jane Doe, co-founder and CEO"
    re.compile(r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,3}),\s+(?:CEO|co-?founder|founder|CTO|MD)"),
    # "said Jane Doe, founder" / "according to Jane Doe, CEO"
    re.compile(r"(?:said|according to|says?)\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3}),\s+(?:CEO|co-?founder|founder|CTO|MD)"),
    # "co-founder Jane Doe" / "founder Jane Doe"
    re.compile(r"\b(?:co-?founder|founder)\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})"),
    # "Jane Doe, who founded" / "Jane Doe, who co-founded"
    re.compile(r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,3}),\s+who\s+(?:co-?)?founded"),
]

# Common false positives (non-person proper nouns that match name patterns)
_FOUNDER_NOISE = {
    "Series A", "Series B", "Series C", "Series D", "New York", "San Francisco",
    "Silicon Valley", "South Asia", "Southeast Asia", "Latin America", "East Asia",
    "North America", "United States", "United Kingdom", "South Africa",
    "General Catalyst", "Tiger Global", "Sequoia Capital", "Y Combinator",
    "Google Ventures", "Microsoft Ventures", "Amazon Web",
}


def parse_founder(text: str, company_name: str = "") -> tuple[Optional[str], Optional[str]]:
    """
    Extract founder/CEO name from article text.
    Returns (founder_name, linkedin_search_url) or (None, None).
    """
    for pattern in _FOUNDER_PATTERNS:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            # Must look like a real name (2+ words, reasonable length)
            parts = name.split()
            if len(parts) < 2 or len(name) > 50:
                continue
            if name in _FOUNDER_NOISE:
                continue
            # Build LinkedIn search URL
            query = name.replace(" ", "+")
            if company_name and company_name != "Unknown":
                query += "+" + company_name.replace(" ", "+")
            linkedin_url = f"https://www.linkedin.com/search/results/people/?keywords={query}"
            return name, linkedin_url
    return None, None




def content_hash(company: str, amount: Optional[float], date: Optional[str]) -> str:
    key = f"{company.lower()}|{amount or ''}|{date or ''}"
    return hashlib.sha1(key.encode()).hexdigest()


# ── Confidence scoring ────────────────────────────────────────────────────────

def compute_confidence(amount: Optional[float], round_type: str,
                       investors: List[str], source_name: str,
                       has_company: bool) -> float:
    score = 0.0
    if amount:                  score += 0.35
    if round_type != "unknown": score += 0.2
    if investors:               score += 0.2
    if has_company:             score += 0.1
    trusted = {"techcrunch", "yourstory", "sifted", "the information", "reuters", "bloomberg", "crunchbase"}
    if any(t in source_name.lower() for t in trusted):
        score += 0.15
    return round(min(score, 1.0), 2)
