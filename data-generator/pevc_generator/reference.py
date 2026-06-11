"""Reference data and weighted distributions for PE/VC realism.

These weights are the credibility gate. A PE tech lead will spot
uniform-random sector allocation immediately, so the distributions
below are deliberately skewed to match real-world PE concentration.
"""

from __future__ import annotations

# Fund strategies — buyout dominates by AUM but VC counts more funds
FUND_STRATEGIES = ["Buyout", "Growth Equity", "Venture Capital", "Secondaries"]
FUND_STRATEGY_WEIGHTS = [0.45, 0.20, 0.30, 0.05]

# Strategy → (size_lognormal_mean_log_usd_m, size_lognormal_sigma)
# Calibrated so medians look right: Buyout ~$1.5B, Growth ~$500M, VC ~$250M, Secondaries ~$2B
STRATEGY_SIZE_PARAMS = {
    "Buyout": (7.3, 0.8),
    "Growth Equity": (6.2, 0.7),
    "Venture Capital": (5.5, 0.9),
    "Secondaries": (7.6, 0.6),
}

FUND_CURRENCIES = ["USD", "EUR", "GBP"]
FUND_CURRENCY_WEIGHTS = [0.70, 0.22, 0.08]

# GP names — fictional, neutral, plausible
GP_NAMES = [
    "Meridian Capital Partners",
    "Northwind Equity",
    "Atlas Bridge Partners",
    "Helios Growth",
    "Korbel Ventures",
    "Stonepath Capital",
    "Verdant Partners",
    "Westgate Equity",
    "Quill & Stone Capital",
    "Ironside Partners",
    "Lighthouse Growth",
    "Cobalt Lane Capital",
]

# LP types — PE-realistic mix
LP_TYPES = [
    "Pension Fund",
    "Sovereign Wealth Fund",
    "Endowment",
    "Family Office",
    "Fund of Funds",
    "Insurance",
]
LP_TYPE_WEIGHTS = [0.32, 0.10, 0.15, 0.20, 0.13, 0.10]

# LP domiciles
LP_DOMICILES = [
    "United States",
    "Canada",
    "United Kingdom",
    "Germany",
    "Switzerland",
    "Netherlands",
    "Singapore",
    "United Arab Emirates",
    "Australia",
    "Japan",
]
LP_DOMICILE_WEIGHTS = [0.32, 0.05, 0.12, 0.08, 0.07, 0.05, 0.08, 0.07, 0.05, 0.11]

# Sectors — weighted to PE concentration (tech and healthcare dominate)
SECTORS = [
    "Information Technology",
    "Healthcare",
    "Financials",
    "Consumer Discretionary",
    "Industrials",
    "Communication Services",
    "Consumer Staples",
    "Energy",
    "Materials",
    "Real Estate",
    "Utilities",
]
SECTOR_WEIGHTS = [0.28, 0.18, 0.10, 0.11, 0.10, 0.07, 0.05, 0.04, 0.03, 0.02, 0.02]

# Geography weights for portfolio companies — North America heavy
COMPANY_COUNTRIES = [
    "United States",
    "Canada",
    "United Kingdom",
    "Germany",
    "France",
    "Netherlands",
    "Sweden",
    "India",
    "Singapore",
    "Australia",
    "Israel",
]
COMPANY_COUNTRY_WEIGHTS = [
    0.50, 0.06, 0.10, 0.07, 0.05, 0.04, 0.03, 0.05, 0.04, 0.03, 0.03,
]

# Deal types
DEAL_TYPES = ["Primary", "Follow-On", "Exit"]

# Valuation methods (for marks)
VALUATION_METHODS = ["DCF", "Comparable Companies", "Comparable Transactions", "Last Round"]
VALUATION_METHOD_WEIGHTS = [0.35, 0.30, 0.20, 0.15]

# Company status
COMPANY_STATUS = ["Active", "Exited", "Written Off"]

# Vintage range — covers a credible PE history window
VINTAGE_MIN = 2010
VINTAGE_MAX = 2024

# Fund lifecycle stage thresholds (years from vintage)
LIFECYCLE_STAGES = [
    (0, 1, "Fundraising"),
    (1, 4, "Investment"),
    (4, 8, "Harvesting"),
    (8, 99, "Winding Down"),
]
