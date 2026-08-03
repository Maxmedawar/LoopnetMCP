"""Stable geographic identifier constants without resolver dependencies."""

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56", "PR": "72",
}

# Keyless city-to-county/CBSA authority shared by the resolver and the access
# boundary.  A restricted result may rely on these relationships only when
# every populated GeoRef carrier agrees with this checked-in mapping.
CITY_FALLBACKS = {
    ("austin", "TX"): ("48453", "12420", "Austin, TX"),
    ("dallas", "TX"): ("48113", "19100", "Dallas, TX"),
    ("houston", "TX"): ("48201", "26420", "Houston, TX"),
    ("san antonio", "TX"): ("48029", "41700", "San Antonio, TX"),
    ("phoenix", "AZ"): ("04013", "38060", "Phoenix, AZ"),
    ("las vegas", "NV"): ("32003", "29820", "Las Vegas, NV"),
    ("miami", "FL"): ("12086", "33100", "Miami, FL"),
    ("fort lauderdale", "FL"): ("12011", "33100", "Fort Lauderdale, FL"),
    ("atlanta", "GA"): ("13121", "12060", "Atlanta, GA"),
    ("charlotte", "NC"): ("37119", "16740", "Charlotte, NC"),
    ("san francisco", "CA"): ("06075", "41860", "San Francisco, CA"),
    ("new york", "NY"): ("36061", "35620", "New York, NY"),
}

# Deliberately limited to county names whose fallback identity is already
# committed and tested by the resolver. Access control treats every county
# outside this exact authority as unresolved rather than guessing.
COUNTY_FIPS = {
    ("travis", "TX"): "48453",
    ("dallas", "TX"): "48113",
    ("harris", "TX"): "48201",
    ("bexar", "TX"): "48029",
    ("tarrant", "TX"): "48439",
    ("los angeles", "CA"): "06037",
    ("san francisco", "CA"): "06075",
    ("new york", "NY"): "36061",
    ("miami-dade", "FL"): "12086",
    ("broward", "FL"): "12011",
    ("maricopa", "AZ"): "04013",
    ("clark", "NV"): "32003",
    ("fulton", "GA"): "13121",
    ("mecklenburg", "NC"): "37119",
    ("cook", "IL"): "17031",
    ("guilford", "NC"): "37081",
    ("yavapai", "AZ"): "04025",
    ("douglas", "CO"): "08035",
}

# Keyless ZIP-to-county/CBSA fallbacks used by the resolver and by the access
# boundary to reconcile duplicated GeoRef and county-sale claims. Unknown ZIP
# cross-level combinations fail closed rather than trusting a supplied FIPS.
ZIP_COUNTY_CBSA = {
    "78701": ("48453", "12420"),  # Travis County / Austin-Round Rock
    "75201": ("48113", "19100"),  # Dallas County / Dallas-Fort Worth
    "77001": ("48201", "26420"),  # Harris County / Houston-The Woodlands
    "94105": ("06075", "41860"),  # San Francisco County / San Francisco-Oakland
    "10001": ("36061", "35620"),  # New York County / New York-Newark
}

__all__ = ["CITY_FALLBACKS", "COUNTY_FIPS", "STATE_FIPS", "ZIP_COUNTY_CBSA"]
