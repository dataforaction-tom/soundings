"""CC area-of-operation description → Soundings LTLA place_id mapping.

The CC bulk ``charity_area_of_operation`` file uses its own LA names
(Title Case, e.g. ``"Durham"``, ``"Birmingham City"``) which don't
match the names in ``geography.place`` (e.g. ``"County Durham"``,
``"Birmingham"``).

This module builds a normalised lookup at load time by querying
``geography.place`` for all ``ltla24`` rows and applying aggressive
normalisation (lowercasing, stripping ``"city of"``/``"county"``/
``"city"``, replacing ``&`` → ``and``, ``-`` → space).  A small set
of manual overrides handles the cases where normalisation alone
can't bridge the gap (e.g. ``"Bournemouth"`` → the merged
``"Bournemouth, Christchurch and Poole"`` LTLA).

~150 of 174 CC LA names auto-match.  The remaining ~24 are historic
county names (``"Devon"``, ``"Essex"``, ``"Kent"`` …) that were never
single LTLAs — those rows are simply skipped (the charity still gets
mapped via its registered-address postcode).
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Manual overrides for CC LA names that can't be auto-matched.
# Value is the ltla24 place_id.  Counties that span multiple LTLAs
# are intentionally absent — they can't be resolved to one place.
_MANUAL_OVERRIDES: dict[str, str] = {
    "bournemouth": "ltla24:E06000058",  # Bournemouth, Christchurch and Poole
    "bristol city": "ltla24:E06000023",  # Bristol, City of
    "city of wakefield": "ltla24:E08000036",  # Wakefield
    "herefordshire": "ltla24:E06000019",  # Herefordshire, County of
    "kingston upon hull city": "ltla24:E06000010",  # Kingston upon Hull, City of
    "poole": "ltla24:E06000058",  # Bournemouth, Christchurch and Poole
    "rhondda cynon taff": "ltla24:W06000016",  # Rhondda Cynon Taf (spelling)
    "city of westminster": "ltla24:E09000033",  # Westminster
    "city of swansea": "ltla24:W06000011",  # Swansea
    "city of york": "ltla24:E06000014",  # York
    "city of london": "ltla24:E09000001",  # City of London
    "newport city": "ltla24:W06000022",  # Newport
    "newcastle upon tyne city": "ltla24:E08000021",  # Newcastle upon Tyne
    "leeds city": "ltla24:E08000035",  # Leeds
    "leicester city": "ltla24:E06000016",  # Leicester
    "nottingham city": "ltla24:E06000018",  # Nottingham
    "derby city": "ltla24:E06000015",  # Derby
    "coventry city": "ltla24:E08000026",  # Coventry
    "bradford city": "ltla24:E08000032",  # Bradford
    "sheffield city": "ltla24:E08000019",  # Sheffield
    "manchester city": "ltla24:E08000003",  # Manchester
    "liverpool city": "ltla24:E08000012",  # Liverpool
    "plymouth city": "ltla24:E06000026",  # Plymouth
    "portsmouth city": "ltla24:E06000044",  # Portsmouth
    "southampton city": "ltla24:E06000045",  # Southampton
    "peterborough city": "ltla24:E06000031",  # Peterborough
    "salford city": "ltla24:E08000006",  # Salford
    "stoke-on-trent city": "ltla24:E06000021",  # Stoke-on-Trent
    "southend-on-sea": "ltla24:E06000033",  # Southend-on-Sea
}


def _normalise(name: str) -> str:
    """Aggressive normalisation for matching CC area descriptions."""
    n = name.lower().strip()
    n = n.replace("city of ", "").replace("county of ", "").replace("county ", "")
    n = n.replace(" city", "")
    n = n.replace(" town", "")
    n = n.replace("&", "and")
    n = n.replace("-", " ")
    n = n.replace(",", "")
    n = n.replace(".", "")
    n = re.sub(r"\s+", " ", n).strip()
    return n


async def build_area_name_to_place_id_map(
    engine: AsyncEngine,
) -> dict[str, str]:
    """Return a dict mapping CC area_description (exact string) → place_id.

    Queries ``geography.place`` for all ``ltla24`` rows, builds a
    normalised-name → place_id index, then matches each known CC LA name
    (from the bulk file) against it.  Manual overrides take precedence.
    """
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("SELECT id, name FROM geography.place WHERE type = 'ltla24'"))
        ).all()

    # Build normalised lookup
    norm_to_place: dict[str, str] = {}
    for row in rows:
        norm = _normalise(row.name)
        if norm and norm not in norm_to_place:
            norm_to_place[norm] = row.id

    # The 174 CC LA names (extracted from the bulk file at build time)
    cc_la_names = [
        "Barking And Dagenham",
        "Barnet",
        "Barnsley",
        "Bath And North East Somerset",
        "Bedford",
        "Bexley",
        "Birmingham City",
        "Blackburn With Darwen",
        "Blackpool",
        "Blaenau Gwent",
        "Bolton",
        "Bournemouth",
        "Bracknell Forest",
        "Bradford City",
        "Brent",
        "Bridgend",
        "Brighton And Hove",
        "Bristol City",
        "Bromley",
        "Buckinghamshire",
        "Bury",
        "Caerphilly",
        "Calderdale",
        "Cambridgeshire",
        "Camden",
        "Cardiff",
        "Carmarthenshire",
        "Central Bedfordshire",
        "Ceredigion",
        "Cheshire East",
        "Cheshire West & Chester",
        "City Of London",
        "City Of Swansea",
        "City Of Wakefield",
        "City Of Westminster",
        "City Of York",
        "Conwy",
        "Cornwall",
        "Coventry City",
        "Croydon",
        "Cumbria",
        "Darlington",
        "Denbighshire",
        "Derby City",
        "Derbyshire",
        "Devon",
        "Doncaster",
        "Dorset",
        "Dudley",
        "Durham",
        "Ealing",
        "East Riding Of Yorkshire",
        "East Sussex",
        "Enfield",
        "Essex",
        "Flintshire",
        "Gateshead",
        "Gloucestershire",
        "Greenwich",
        "Gwynedd",
        "Hackney",
        "Halton",
        "Hammersmith And Fulham",
        "Hampshire",
        "Haringey",
        "Harrow",
        "Hartlepool",
        "Havering",
        "Herefordshire",
        "Hertfordshire",
        "Hillingdon",
        "Hounslow",
        "Isle Of Anglesey",
        "Isle Of Wight",
        "Isles Of Scilly",
        "Islington",
        "Kensington And Chelsea",
        "Kent",
        "Kingston Upon Hull City",
        "Kingston Upon Thames",
        "Kirklees",
        "Knowsley",
        "Lambeth",
        "Lancashire",
        "Leeds City",
        "Leicester City",
        "Leicestershire",
        "Lewisham",
        "Lincolnshire",
        "Liverpool City",
        "Luton",
        "Manchester City",
        "Medway",
        "Merthyr Tydfil",
        "Merton",
        "Middlesbrough",
        "Milton Keynes",
        "Monmouthshire",
        "Neath Port Talbot",
        "Newcastle Upon Tyne City",
        "Newham",
        "Newport City",
        "Norfolk",
        "North East Lincolnshire",
        "North Lincolnshire",
        "North Somerset",
        "North Tyneside",
        "North Yorkshire",
        "Northamptonshire",
        "Northumberland",
        "Nottingham City",
        "Nottinghamshire",
        "Oldham",
        "Oxfordshire",
        "Pembrokeshire",
        "Peterborough City",
        "Plymouth City",
        "Poole",
        "Portsmouth City",
        "Powys",
        "Reading",
        "Redbridge",
        "Redcar And Cleveland",
        "Rhondda Cynon Taff",
        "Richmond Upon Thames",
        "Rochdale",
        "Rotherham",
        "Rutland",
        "Salford City",
        "Sandwell",
        "Sefton",
        "Sheffield City",
        "Shropshire",
        "Slough",
        "Solihull",
        "Somerset",
        "South Gloucestershire",
        "South Tyneside",
        "Southampton City",
        "Southend-on-sea",
        "Southwark",
        "St Helens",
        "Staffordshire",
        "Stockport",
        "Stockton-on-tees",
        "Stoke-on-trent City",
        "Suffolk",
        "Sunderland",
        "Surrey",
        "Sutton",
        "Swindon",
        "Tameside",
        "Telford & Wrekin",
        "Thurrock",
        "Torbay",
        "Torfaen",
        "Tower Hamlets",
        "Trafford",
        "Vale Of Glamorgan",
        "Walsall",
        "Waltham Forest",
        "Wandsworth",
        "Warrington",
        "Warwickshire",
        "West Berkshire",
        "West Sussex",
        "Wigan",
        "Wiltshire",
        "Windsor And Maidenhead",
        "Wirral",
        "Wokingham",
        "Wolverhampton",
        "Worcestershire",
        "Wrexham",
    ]

    mapping: dict[str, str] = {}
    for cc_name in cc_la_names:
        norm_cc = _normalise(cc_name)
        # Manual override first
        if norm_cc in _MANUAL_OVERRIDES:
            mapping[cc_name] = _MANUAL_OVERRIDES[norm_cc]
            continue
        # Auto-match
        if norm_cc in norm_to_place:
            mapping[cc_name] = norm_to_place[norm_cc]
            continue
        # Try without "city" suffix (already stripped by _normalise, but
        # in case the place name still has it)
        # Skip — no match (historic counties like "Devon", "Essex")
    return mapping
