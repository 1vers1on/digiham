"""Lightweight DXCC / country resolution from a callsign prefix.

This turns a callsign into a best-guess DXCC entity name and continent so
decodes can be annotated with the country and continent, and so the engine
can flag *new* countries you have not worked (the "new DXCC" alert WSJT-X
users lean on for chasing awards).

It is deliberately self-contained: a curated prefix table (no external
data file), matched longest-prefix-first, with a little callsign cleanup so
portable designators such as ``F/W1ABC`` or ``W1ABC/VP9`` resolve to the
operating country rather than the home one. It is not a substitute for a
full cty.dat lookup — it covers the common DX world, not every exception —
but it is accurate for the overwhelming majority of on-air calls and needs
nothing but the standard library.

Beyond the table itself, the resolver knows a few on-air realities:

* protocol tokens that are not callsigns (``CQ``, ``RR73``, ``QRZ`` …)
  resolve to nothing rather than to whichever country their letters
  happen to spell;
* ``/MM`` (maritime mobile) and ``/AM`` (aeronautical mobile) count as
  *no* DXCC entity, per the award rules;
* hashed compound calls from FT8/FT4 (``<W1ABC>``, ``<...>``) and stray
  whitespace/punctuation are cleaned up before matching;
* ``KG4`` + a two-letter suffix is Guantanamo Bay, while any other KG4
  call is the ordinary United States — the classic prefix exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

# Continent codes: AF Africa, AN Antarctica, AS Asia, EU Europe,
# NA North America, OC Oceania, SA South America.


@dataclass(frozen=True)
class Entity:
    name: str
    continent: str


# Pairs of (prefix, (name, continent)). Longest prefixes are matched first,
# so specific prefixes like "KH6" win over the generic "K". This is a
# working subset of the ~340 DXCC entities, weighted towards the ones
# actually heard on the digital bands.
_TABLE: dict[str, tuple[str, str]] = {
    # --- North America -------------------------------------------------
    "K": ("United States", "NA"), "W": ("United States", "NA"),
    "N": ("United States", "NA"), "AA": ("United States", "NA"),
    "AB": ("United States", "NA"), "AC": ("United States", "NA"),
    "AD": ("United States", "NA"), "AE": ("United States", "NA"),
    "AF": ("United States", "NA"), "AG": ("United States", "NA"),
    "AI": ("United States", "NA"), "AJ": ("United States", "NA"),
    "AK": ("United States", "NA"),
    "KL": ("Alaska", "NA"), "KL7": ("Alaska", "NA"), "AL": ("Alaska", "NA"),
    "NL": ("Alaska", "NA"), "WL": ("Alaska", "NA"),
    "KH6": ("Hawaii", "OC"), "KH7": ("Hawaii", "OC"), "NH6": ("Hawaii", "OC"),
    "WH6": ("Hawaii", "OC"), "AH6": ("Hawaii", "OC"),
    "KH2": ("Guam", "OC"), "NH2": ("Guam", "OC"), "AH2": ("Guam", "OC"),
    "KH0": ("Mariana Is", "OC"), "KH8": ("American Samoa", "OC"),
    "KH9": ("Wake I", "OC"), "KH1": ("Baker Howland", "OC"),
    "KH3": ("Johnston I", "OC"), "KH4": ("Midway I", "OC"),
    "KH5": ("Palmyra Jarvis", "OC"),
    "KP4": ("Puerto Rico", "NA"), "KP3": ("Puerto Rico", "NA"),
    "NP4": ("Puerto Rico", "NA"), "WP4": ("Puerto Rico", "NA"),
    "KP2": ("US Virgin Is", "NA"), "KP1": ("Navassa I", "NA"),
    "KP5": ("Desecheo I", "NA"),
    "VE": ("Canada", "NA"), "VA": ("Canada", "NA"), "VO": ("Canada", "NA"),
    "VY": ("Canada", "NA"), "CY0": ("Sable I", "NA"), "CY9": ("St Paul I", "NA"),
    "XE": ("Mexico", "NA"), "XF": ("Mexico", "NA"),
    "XF4": ("Revillagigedo", "NA"),
    "CO": ("Cuba", "NA"), "CM": ("Cuba", "NA"),
    "HH": ("Haiti", "NA"), "HI": ("Dominican Rep", "NA"),
    "6Y": ("Jamaica", "NA"), "8P": ("Barbados", "NA"),
    "V2": ("Antigua Barbuda", "NA"), "V3": ("Belize", "NA"),
    "TG": ("Guatemala", "NA"), "YS": ("El Salvador", "NA"),
    "HR": ("Honduras", "NA"), "YN": ("Nicaragua", "NA"),
    "TI": ("Costa Rica", "NA"), "TI9": ("Cocos I", "NA"),
    "HP": ("Panama", "NA"),
    "C6": ("Bahamas", "NA"), "ZF": ("Cayman Is", "NA"),
    "VP2E": ("Anguilla", "NA"), "VP2M": ("Montserrat", "NA"),
    "VP2V": ("British Virgin Is", "NA"), "VP5": ("Turks Caicos", "NA"),
    "VP9": ("Bermuda", "NA"), "FM": ("Martinique", "NA"),
    "FG": ("Guadeloupe", "NA"), "FJ": ("St Barthelemy", "NA"),
    "FP": ("St Pierre Miquelon", "NA"), "J3": ("Grenada", "NA"),
    "J6": ("St Lucia", "NA"), "J7": ("Dominica", "NA"),
    "J8": ("St Vincent", "NA"), "V4": ("St Kitts Nevis", "NA"),
    "PJ": ("Curacao", "NA"), "PJ2": ("Curacao", "NA"), "PJ4": ("Bonaire", "NA"),
    "PJ5": ("Saba St Eustatius", "NA"), "PJ6": ("Saba St Eustatius", "NA"),
    "PJ7": ("Sint Maarten", "NA"), "FS": ("St Martin", "NA"),
    # --- South America -------------------------------------------------
    "PY": ("Brazil", "SA"), "PP": ("Brazil", "SA"), "PT": ("Brazil", "SA"),
    "PU": ("Brazil", "SA"), "PR": ("Brazil", "SA"), "PS": ("Brazil", "SA"),
    "PY0F": ("Fernando de Noronha", "SA"), "PV": ("Brazil", "SA"),
    "LU": ("Argentina", "SA"), "AY": ("Argentina", "SA"),
    "AZ": ("Argentina", "SA"),
    "LO": ("Argentina", "SA"), "LP": ("Argentina", "SA"),
    "LQ": ("Argentina", "SA"), "LR": ("Argentina", "SA"),
    "LS": ("Argentina", "SA"), "LT": ("Argentina", "SA"),
    "LV": ("Argentina", "SA"), "LW": ("Argentina", "SA"),
    "L2": ("Argentina", "SA"), "L3": ("Argentina", "SA"),
    "L4": ("Argentina", "SA"), "L5": ("Argentina", "SA"),
    "L6": ("Argentina", "SA"), "L7": ("Argentina", "SA"),
    "L8": ("Argentina", "SA"), "L9": ("Argentina", "SA"),
    "CE": ("Chile", "SA"),
    "CE0": ("Easter I", "SA"), "CE0Y": ("Easter I", "SA"),
    "CE0Z": ("Juan Fernandez", "SA"), "CE0X": ("San Felix", "SA"),
    "CX": ("Uruguay", "SA"),
    "CP": ("Bolivia", "SA"), "HK": ("Colombia", "SA"),
    "HK0": ("San Andres", "NA"),
    "HC": ("Ecuador", "SA"), "HC8": ("Galapagos", "SA"),
    "OA": ("Peru", "SA"), "YV": ("Venezuela", "SA"),
    "9Y": ("Trinidad Tobago", "SA"), "9Z": ("Trinidad Tobago", "SA"),
    "8R": ("Guyana", "SA"), "PZ": ("Suriname", "SA"),
    "FY": ("French Guiana", "SA"), "ZP": ("Paraguay", "SA"),
    "VP8": ("Falkland Is", "SA"),
    # --- Europe --------------------------------------------------------
    "G": ("England", "EU"), "M": ("England", "EU"), "2E": ("England", "EU"),
    "GB": ("England", "EU"),
    "GM": ("Scotland", "EU"), "MM": ("Scotland", "EU"), "2M": ("Scotland", "EU"),
    "GW": ("Wales", "EU"), "MW": ("Wales", "EU"), "2W": ("Wales", "EU"),
    "GI": ("Northern Ireland", "EU"), "MI": ("Northern Ireland", "EU"),
    "2I": ("Northern Ireland", "EU"),
    "GD": ("Isle of Man", "EU"), "MD": ("Isle of Man", "EU"),
    "2D": ("Isle of Man", "EU"),
    "GJ": ("Jersey", "EU"), "MJ": ("Jersey", "EU"), "2J": ("Jersey", "EU"),
    "GU": ("Guernsey", "EU"), "MU": ("Guernsey", "EU"),
    "2U": ("Guernsey", "EU"),
    "EI": ("Ireland", "EU"), "EJ": ("Ireland", "EU"),
    "F": ("France", "EU"), "TM": ("France", "EU"),
    "DL": ("Germany", "EU"), "DK": ("Germany", "EU"), "DJ": ("Germany", "EU"),
    "DA": ("Germany", "EU"), "DB": ("Germany", "EU"), "DC": ("Germany", "EU"),
    "DD": ("Germany", "EU"), "DF": ("Germany", "EU"), "DG": ("Germany", "EU"),
    "DH": ("Germany", "EU"), "DM": ("Germany", "EU"), "DO": ("Germany", "EU"),
    "PA": ("Netherlands", "EU"), "PB": ("Netherlands", "EU"),
    "PC": ("Netherlands", "EU"), "PD": ("Netherlands", "EU"),
    "PE": ("Netherlands", "EU"), "PF": ("Netherlands", "EU"),
    "PG": ("Netherlands", "EU"), "PH": ("Netherlands", "EU"),
    "ON": ("Belgium", "EU"), "OO": ("Belgium", "EU"), "OT": ("Belgium", "EU"),
    "LX": ("Luxembourg", "EU"), "HB": ("Switzerland", "EU"),
    "HB0": ("Liechtenstein", "EU"), "OE": ("Austria", "EU"),
    "I": ("Italy", "EU"), "IS0": ("Sardinia", "EU"), "IM0": ("Sardinia", "EU"),
    "EA": ("Spain", "EU"), "EB": ("Spain", "EU"), "EC": ("Spain", "EU"),
    "ED": ("Spain", "EU"), "EE": ("Spain", "EU"), "EF": ("Spain", "EU"),
    "EA6": ("Balearic Is", "EU"), "EA8": ("Canary Is", "AF"),
    "EA9": ("Ceuta Melilla", "AF"), "ZB": ("Gibraltar", "EU"),
    "CT": ("Portugal", "EU"), "CT3": ("Madeira", "AF"), "CU": ("Azores", "EU"),
    "OH": ("Finland", "EU"), "OH0": ("Aland Is", "EU"), "OG": ("Finland", "EU"),
    "OF": ("Finland", "EU"), "OJ0": ("Market Reef", "EU"),
    "SM": ("Sweden", "EU"), "SA": ("Sweden", "EU"), "SB": ("Sweden", "EU"),
    "SK": ("Sweden", "EU"), "SL": ("Sweden", "EU"), "7S": ("Sweden", "EU"),
    "8S": ("Sweden", "EU"),
    "LA": ("Norway", "EU"), "LB": ("Norway", "EU"), "LC": ("Norway", "EU"),
    "LD": ("Norway", "EU"), "LE": ("Norway", "EU"), "LF": ("Norway", "EU"),
    "LG": ("Norway", "EU"), "LH": ("Norway", "EU"), "LI": ("Norway", "EU"),
    "LJ": ("Norway", "EU"), "LK": ("Norway", "EU"), "LL": ("Norway", "EU"),
    "LM": ("Norway", "EU"), "LN": ("Norway", "EU"),
    "JW": ("Svalbard", "EU"), "JX": ("Jan Mayen", "EU"),
    "OZ": ("Denmark", "EU"), "OU": ("Denmark", "EU"), "OV": ("Denmark", "EU"),
    "OW": ("Denmark", "EU"), "5P": ("Denmark", "EU"), "5Q": ("Denmark", "EU"),
    "OY": ("Faroe Is", "EU"), "OX": ("Greenland", "NA"),
    "TF": ("Iceland", "EU"),
    "SP": ("Poland", "EU"), "SN": ("Poland", "EU"), "SO": ("Poland", "EU"),
    "SQ": ("Poland", "EU"), "HF": ("Poland", "EU"), "3Z": ("Poland", "EU"),
    "OK": ("Czech Rep", "EU"), "OL": ("Czech Rep", "EU"),
    "OM": ("Slovakia", "EU"), "HA": ("Hungary", "EU"), "HG": ("Hungary", "EU"),
    "YU": ("Serbia", "EU"), "YT": ("Serbia", "EU"), "YZ": ("Serbia", "EU"),
    "9A": ("Croatia", "EU"), "S5": ("Slovenia", "EU"),
    "E7": ("Bosnia-Herz", "EU"), "Z3": ("North Macedonia", "EU"),
    "ZA": ("Albania", "EU"), "Z6": ("Kosovo", "EU"),
    "4O": ("Montenegro", "EU"),
    "LZ": ("Bulgaria", "EU"), "YO": ("Romania", "EU"), "YP": ("Romania", "EU"),
    "YR": ("Romania", "EU"), "ER": ("Moldova", "EU"),
    "SV": ("Greece", "EU"), "SW": ("Greece", "EU"), "SX": ("Greece", "EU"),
    "SY": ("Greece", "EU"), "SV5": ("Dodecanese", "EU"),
    "SV9": ("Crete", "EU"), "9H": ("Malta", "EU"),
    "TK": ("Corsica", "EU"), "T7": ("San Marino", "EU"),
    "HV": ("Vatican", "EU"), "1A": ("SMOM", "EU"), "3A": ("Monaco", "EU"),
    "C3": ("Andorra", "EU"),
    "YL": ("Latvia", "EU"), "LY": ("Lithuania", "EU"),
    "ES": ("Estonia", "EU"), "UA": ("Russia", "EU"), "UB": ("Russia", "EU"),
    "UC": ("Russia", "EU"), "UD": ("Russia", "EU"), "UE": ("Russia", "EU"),
    "UF": ("Russia", "EU"), "UG": ("Russia", "EU"), "UH": ("Russia", "EU"),
    "UI": ("Russia", "EU"), "R": ("Russia", "EU"),
    "UA2": ("Kaliningrad", "EU"), "RA2": ("Kaliningrad", "EU"),
    "UA9": ("Russia (Asia)", "AS"), "UA0": ("Russia (Asia)", "AS"),
    "RA9": ("Russia (Asia)", "AS"), "RA0": ("Russia (Asia)", "AS"),
    "EU": ("Belarus", "EU"), "EV": ("Belarus", "EU"), "EW": ("Belarus", "EU"),
    "UR": ("Ukraine", "EU"), "US": ("Ukraine", "EU"), "UT": ("Ukraine", "EU"),
    "UU": ("Ukraine", "EU"), "UV": ("Ukraine", "EU"), "UW": ("Ukraine", "EU"),
    "UX": ("Ukraine", "EU"), "UY": ("Ukraine", "EU"), "UZ": ("Ukraine", "EU"),
    "EM": ("Ukraine", "EU"), "EO": ("Ukraine", "EU"),
    # --- Asia ----------------------------------------------------------
    "JA": ("Japan", "AS"), "JE": ("Japan", "AS"), "JF": ("Japan", "AS"),
    "JG": ("Japan", "AS"), "JH": ("Japan", "AS"), "JI": ("Japan", "AS"),
    "JJ": ("Japan", "AS"), "JK": ("Japan", "AS"), "JL": ("Japan", "AS"),
    "JM": ("Japan", "AS"), "JN": ("Japan", "AS"), "JO": ("Japan", "AS"),
    "JP": ("Japan", "AS"), "JQ": ("Japan", "AS"), "JR": ("Japan", "AS"),
    "JS": ("Japan", "AS"), "7J": ("Japan", "AS"), "7K": ("Japan", "AS"),
    "7L": ("Japan", "AS"), "7M": ("Japan", "AS"), "7N": ("Japan", "AS"),
    "8J": ("Japan", "AS"), "JD1": ("Ogasawara", "AS"),
    "B": ("China", "AS"),
    "BY": ("China", "AS"), "BA": ("China", "AS"), "BD": ("China", "AS"),
    "BG": ("China", "AS"), "BH": ("China", "AS"),
    "BM": ("Taiwan", "AS"), "BN": ("Taiwan", "AS"), "BO": ("Taiwan", "AS"),
    "BP": ("Taiwan", "AS"), "BQ": ("Taiwan", "AS"), "BU": ("Taiwan", "AS"),
    "BV": ("Taiwan", "AS"), "BW": ("Taiwan", "AS"), "BX": ("Taiwan", "AS"),
    "VR": ("Hong Kong", "AS"), "XX9": ("Macao", "AS"),
    "HL": ("South Korea", "AS"), "DS": ("South Korea", "AS"),
    "DT": ("South Korea", "AS"),
    "6K": ("South Korea", "AS"), "6L": ("South Korea", "AS"),
    "6M": ("South Korea", "AS"), "6N": ("South Korea", "AS"),
    "P5": ("North Korea", "AS"),
    "VU": ("India", "AS"), "AT": ("India", "AS"), "8T": ("India", "AS"),
    "VU4": ("Andaman Nicobar", "AS"), "VU7": ("Lakshadweep", "AS"),
    "4S": ("Sri Lanka", "AS"), "S2": ("Bangladesh", "AS"),
    "8Q": ("Maldives", "AS"),
    "AP": ("Pakistan", "AS"), "9N": ("Nepal", "AS"), "A5": ("Bhutan", "AS"),
    "HS": ("Thailand", "AS"), "E2": ("Thailand", "AS"),
    "XU": ("Cambodia", "AS"), "XW": ("Laos", "AS"), "XZ": ("Myanmar", "AS"),
    "3W": ("Vietnam", "AS"), "XV": ("Vietnam", "AS"),
    "9M2": ("West Malaysia", "AS"), "9M6": ("East Malaysia", "OC"),
    "9V": ("Singapore", "AS"), "YB": ("Indonesia", "OC"),
    "YC": ("Indonesia", "OC"), "YD": ("Indonesia", "OC"),
    "YE": ("Indonesia", "OC"), "YF": ("Indonesia", "OC"),
    "YG": ("Indonesia", "OC"), "YH": ("Indonesia", "OC"),
    "DU": ("Philippines", "OC"), "DV": ("Philippines", "OC"),
    "DW": ("Philippines", "OC"), "DX": ("Philippines", "OC"),
    "DY": ("Philippines", "OC"), "DZ": ("Philippines", "OC"),
    "V8": ("Brunei", "OC"), "4W": ("Timor-Leste", "OC"),
    "4J": ("Azerbaijan", "AS"), "4K": ("Azerbaijan", "AS"),
    "EK": ("Armenia", "AS"), "4L": ("Georgia", "AS"),
    "EX": ("Kyrgyzstan", "AS"), "EY": ("Tajikistan", "AS"),
    "EZ": ("Turkmenistan", "AS"), "UK": ("Uzbekistan", "AS"),
    "UN": ("Kazakhstan", "AS"), "UP": ("Kazakhstan", "AS"),
    "UQ": ("Kazakhstan", "AS"),
    "TA": ("Turkey", "AS"), "TB": ("Turkey", "AS"), "TC": ("Turkey", "AS"),
    "YM": ("Turkey", "AS"),
    "5B": ("Cyprus", "AS"), "C4": ("Cyprus", "AS"), "H2": ("Cyprus", "AS"),
    "ZC4": ("UK Bases Cyprus", "AS"),
    "4X": ("Israel", "AS"), "4Z": ("Israel", "AS"), "E4": ("Palestine", "AS"),
    "JY": ("Jordan", "AS"),
    "OD": ("Lebanon", "AS"), "YK": ("Syria", "AS"), "YI": ("Iraq", "AS"),
    "EP": ("Iran", "AS"), "EQ": ("Iran", "AS"),
    "A4": ("Oman", "AS"), "A6": ("United Arab Emirates", "AS"),
    "A7": ("Qatar", "AS"), "A9": ("Bahrain", "AS"),
    "HZ": ("Saudi Arabia", "AS"), "7Z": ("Saudi Arabia", "AS"),
    "8Z": ("Saudi Arabia", "AS"), "9K": ("Kuwait", "AS"),
    "7O": ("Yemen", "AS"),
    "YA": ("Afghanistan", "AS"), "T6": ("Afghanistan", "AS"),
    # --- Africa --------------------------------------------------------
    "ZS": ("South Africa", "AF"), "ZR": ("South Africa", "AF"),
    "ZT": ("South Africa", "AF"), "ZU": ("South Africa", "AF"),
    "ZS8": ("Marion I", "AF"),
    "SU": ("Egypt", "AF"), "CN": ("Morocco", "AF"),
    "S0": ("Western Sahara", "AF"),
    "7X": ("Algeria", "AF"), "3V": ("Tunisia", "AF"),
    "5A": ("Libya", "AF"), "ST": ("Sudan", "AF"), "Z8": ("South Sudan", "AF"),
    "ET": ("Ethiopia", "AF"), "E3": ("Eritrea", "AF"),
    "J2": ("Djibouti", "AF"), "T5": ("Somalia", "AF"), "6O": ("Somalia", "AF"),
    "5Z": ("Kenya", "AF"),
    "5H": ("Tanzania", "AF"), "5X": ("Uganda", "AF"), "9U": ("Burundi", "AF"),
    "9X": ("Rwanda", "AF"), "5R": ("Madagascar", "AF"),
    "3B8": ("Mauritius", "AF"), "3B9": ("Rodrigues I", "AF"),
    "3B6": ("Agalega", "AF"), "S7": ("Seychelles", "AF"),
    "D4": ("Cape Verde", "AF"), "D6": ("Comoros", "AF"),
    "5N": ("Nigeria", "AF"), "9G": ("Ghana", "AF"), "TU": ("Ivory Coast", "AF"),
    "TY": ("Benin", "AF"), "5V": ("Togo", "AF"),
    "TT": ("Chad", "AF"), "TL": ("Central Africa", "AF"),
    "TJ": ("Cameroon", "AF"), "TR": ("Gabon", "AF"),
    "TN": ("Congo", "AF"), "9Q": ("Dem Rep Congo", "AF"),
    "D2": ("Angola", "AF"), "D3": ("Angola", "AF"),
    "C8": ("Mozambique", "AF"), "C9": ("Mozambique", "AF"),
    "Z2": ("Zimbabwe", "AF"), "7Q": ("Malawi", "AF"), "9J": ("Zambia", "AF"),
    "V5": ("Namibia", "AF"), "A2": ("Botswana", "AF"), "3DA": ("Eswatini", "AF"),
    "7P": ("Lesotho", "AF"), "6W": ("Senegal", "AF"), "6V": ("Senegal", "AF"),
    "C5": ("Gambia", "AF"),
    "3X": ("Guinea", "AF"), "9L": ("Sierra Leone", "AF"),
    "EL": ("Liberia", "AF"), "XT": ("Burkina Faso", "AF"),
    "5U": ("Niger", "AF"), "5T": ("Mauritania", "AF"), "TZ": ("Mali", "AF"),
    "J5": ("Guinea-Bissau", "AF"), "S9": ("Sao Tome", "AF"),
    "3C": ("Equatorial Guinea", "AF"), "ZD7": ("St Helena", "AF"),
    "ZD8": ("Ascension I", "AF"), "ZD9": ("Tristan da Cunha", "AF"),
    "FT5": ("French Antarctic", "AF"), "FR": ("Reunion I", "AF"),
    "FH": ("Mayotte", "AF"), "VQ9": ("Chagos Is", "AF"),
    # --- Oceania -------------------------------------------------------
    "VK": ("Australia", "OC"), "AX": ("Australia", "OC"),
    "VK9": ("Australia (ext)", "OC"), "VK9C": ("Cocos Keeling", "OC"),
    "VK9L": ("Lord Howe I", "OC"), "VK9N": ("Norfolk I", "OC"),
    "VK9X": ("Christmas I", "OC"), "VK0": ("Heard I", "AN"),
    "ZL": ("New Zealand", "OC"), "ZM": ("New Zealand", "OC"),
    "ZL7": ("Chatham Is", "OC"), "ZL8": ("Kermadec Is", "OC"),
    "ZL9": ("NZ Subantarctic Is", "OC"),
    "E5": ("Cook Is", "OC"), "E6": ("Niue", "OC"),
    "5W": ("Samoa", "OC"), "A3": ("Tonga", "OC"), "A35": ("Tonga", "OC"),
    "3D2": ("Fiji", "OC"), "3D2R": ("Rotuma I", "OC"),
    "YJ": ("Vanuatu", "OC"), "H4": ("Solomon Is", "OC"),
    "H40": ("Temotu", "OC"),
    "P2": ("Papua New Guinea", "OC"), "T2": ("Tuvalu", "OC"),
    "T30": ("W Kiribati", "OC"), "T31": ("C Kiribati", "OC"),
    "T32": ("E Kiribati", "OC"), "T33": ("Banaba I", "OC"),
    "C2": ("Nauru", "OC"), "V6": ("Micronesia", "OC"),
    "V7": ("Marshall Is", "OC"), "KC6": ("Palau", "OC"), "T8": ("Palau", "OC"),
    "FO": ("French Polynesia", "OC"), "FK": ("New Caledonia", "OC"),
    "FW": ("Wallis Futuna", "OC"), "ZK3": ("Tokelau", "OC"),
    "9M8": ("East Malaysia", "OC"),
    # --- Antarctica / special ------------------------------------------
    "CE9": ("Antarctica", "AN"), "KC4": ("Antarctica", "AN"),
    "8J1": ("Antarctica", "AN"), "DP0": ("Antarctica", "AN"),
    "RI1": ("Antarctica", "AN"), "3Y": ("Bouvet", "AN"),
    "4U1UN": ("United Nations HQ", "NA"), "4U1ITU": ("ITU HQ", "EU"),
}

_MAX_PREFIX_LEN = max(map(len, _TABLE))

# Portable designators that are *suffixes*, never a country override.
_SUFFIX_ONLY = {"P", "M", "QRP", "QRPP", "A", "R", "B", "T", "LH"}

# Slashed designators that place the station outside any DXCC entity:
# maritime mobile and aeronautical mobile count for no country under the
# award rules, so /MM and /AM resolve to None rather than the home call.
_NO_ENTITY = {"MM", "AM"}

# Procedural tokens that could otherwise pass the structural check and
# match a prefix (e.g. RR73 -> "R" -> Russia). Pure-letter or pure-digit
# tokens (CQ, QRZ, 73, RRR...) are already rejected structurally.
_NOT_CALLSIGNS = frozenset({"RR73"})

# The whole cleaned call must be built from these characters.
_CHARSET_RE = re.compile(r"[A-Z0-9/]+")

# KG4 + exactly two letters is Guantanamo Bay; longer KG4 calls are
# ordinary US stations. The best-known "prefix isn't enough" exception.
_KG4_GITMO_RE = re.compile(r"KG4[A-Z]{2}")


def _match(token: str) -> Optional[Entity]:
    """Longest-prefix match of *token* against the table."""
    for n in range(min(len(token), _MAX_PREFIX_LEN), 0, -1):
        hit = _TABLE.get(token[:n])
        if hit is not None:
            return Entity(*hit)
    return None


def _exception(token: str) -> Optional[Entity]:
    """Entities that hinge on the *shape* of the call, not just its prefix."""
    if _KG4_GITMO_RE.fullmatch(token):
        return Entity("Guantanamo Bay", "NA")
    return None


def _designator(call: str) -> Optional[str]:
    """Reduce a (possibly portable) call to the token that carries its DXCC.

    ``F/W1ABC`` -> ``F`` (operating in France); ``W1ABC/VP9`` -> ``VP9``
    (operating in Bermuda); ``W1ABC/P`` -> ``W1ABC`` (a suffix, home call).
    ``W1ABC/MM`` -> ``None`` (maritime mobile counts for no entity).
    """
    if "/" not in call:
        return call
    parts = [p for p in call.split("/") if p]
    if not parts:
        return None
    if any(p in _NO_ENTITY for p in parts[1:]):
        return None
    # Drop pure suffixes and single-digit district markers.
    meaningful = [p for p in parts
                  if p not in _SUFFIX_ONLY and not (len(p) == 1 and p.isdigit())]
    if not meaningful:
        return parts[0]
    # A prefix override is the shortest meaningful token that resolves in the
    # table (e.g. "VP9" over "W1ABC"); prefixes are short, home calls long.
    meaningful.sort(key=len)
    for tok in meaningful:
        if _match(tok) is not None:
            return tok
    # Nothing resolves as an override: fall back to the longest token, which
    # is normally the actual callsign.
    return max(meaningful, key=len)


def _plausible_call(call: str) -> bool:
    """Structural sanity check: real amateur calls run three or more chars
    and always mix at least one letter with at least one digit. Rejects
    procedural tokens (CQ, QRZ, 73, RRR...) and free-text junk that would
    otherwise coincidentally match a prefix."""
    if len(call) < 3 or call in _NOT_CALLSIGNS:
        return False
    if not _CHARSET_RE.fullmatch(call):
        return False
    return (any(c.isdigit() for c in call)
            and any(c.isalpha() for c in call))


@lru_cache(maxsize=4096)
def lookup(call: Optional[str]) -> Optional[Entity]:
    """Best-guess :class:`Entity` for *call*, or ``None`` if unresolved.

    Tolerates the junk that shows up in real decode streams: surrounding
    whitespace, FT8 hashed-call brackets (``<W1ABC>``, ``<...>``), stray
    punctuation, and lowercase input.
    """
    if not call:
        return None
    call = call.upper().strip(" \t<>.,:;!?")
    if not _plausible_call(call):
        return None
    token = _designator(call)
    if token is None:
        return None
    return _exception(token) or _match(token)


def country(call: str) -> str:
    """Entity name for *call*, or ``""``."""
    e = lookup(call)
    return e.name if e else ""


def continent(call: str) -> str:
    """Continent code (e.g. ``"EU"``) for *call*, or ``""``."""
    e = lookup(call)
    return e.continent if e else ""
