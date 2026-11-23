"""Curated OSM tag definitions for place-bounded feature extraction.

Each category lists exactly the OSM tags that mean that thing, so "hospitals"
returns hospitals (not clinics or pharmacies) and "malls" returns malls (not
every shop). `mode` decides the output geometry:

* "point"    — one point per facility (node position, or the centre of the
               mapped building/campus/relation). Used for counting & plotting
               facilities; each facility is counted once.
* "geometry" — the real line/polygon geometry, clipped to the boundary (roads,
               rail, waterways, parks, land use, buildings).
"""

from __future__ import annotations

# (key, value) — value None means "any value of this key"; "a|b" means any of.
OSM_CATEGORIES: dict[str, dict] = {
    "hospitals": {"label": "Hospitals", "color": "#dc2626", "mode": "point",
                  "tags": [("amenity", "hospital"), ("healthcare", "hospital")]},
    "clinics": {"label": "Clinics & Doctors", "color": "#f87171", "mode": "point",
                "tags": [("amenity", "clinic|doctors"), ("healthcare", "clinic|doctor|centre")]},
    "pharmacies": {"label": "Pharmacies", "color": "#fb7185", "mode": "point",
                   "tags": [("amenity", "pharmacy"), ("healthcare", "pharmacy")]},
    "schools": {"label": "Schools", "color": "#2563eb", "mode": "point", "tags": [("amenity", "school")]},
    "colleges": {"label": "Colleges", "color": "#7c3aed", "mode": "point", "tags": [("amenity", "college")]},
    "universities": {"label": "Universities", "color": "#6d28d9", "mode": "point", "tags": [("amenity", "university")]},
    "kindergartens": {"label": "Kindergartens", "color": "#60a5fa", "mode": "point", "tags": [("amenity", "kindergarten|childcare")]},
    "offices": {"label": "Offices", "color": "#0891b2", "mode": "point",
                "tags": [("office", None), ("building", "office")]},
    "government_offices": {"label": "Government Offices", "color": "#0e7490", "mode": "point",
                           "tags": [("office", "government|administrative"), ("amenity", "townhall|courthouse")]},
    "it_offices": {"label": "IT & Company Offices", "color": "#155e75", "mode": "point",
                   "tags": [("office", "it|company")]},
    "commercial_areas": {"label": "Commercial Areas", "color": "#be185d", "mode": "geometry",
                         "tags": [("landuse", "commercial|retail")]},
    "malls": {"label": "Malls", "color": "#c026d3", "mode": "point", "tags": [("shop", "mall")]},
    "department_stores": {"label": "Department Stores", "color": "#a21caf", "mode": "point", "tags": [("shop", "department_store")]},
    "supermarkets": {"label": "Supermarkets", "color": "#d946ef", "mode": "point", "tags": [("shop", "supermarket")]},
    "markets": {"label": "Markets", "color": "#e879f9", "mode": "point", "tags": [("amenity", "marketplace")]},
    "shops": {"label": "Shops", "color": "#f0abfc", "mode": "point", "tags": [("shop", None)]},
    "restaurants": {"label": "Restaurants & Cafés", "color": "#f97316", "mode": "point", "tags": [("amenity", "restaurant|cafe|fast_food|food_court")]},
    "hotels": {"label": "Hotels", "color": "#ea580c", "mode": "point", "tags": [("tourism", "hotel|guest_house|hostel|motel")]},
    "banks": {"label": "Banks", "color": "#16a34a", "mode": "point", "tags": [("amenity", "bank")]},
    "atms": {"label": "ATMs", "color": "#22c55e", "mode": "point", "tags": [("amenity", "atm")]},
    "police": {"label": "Police Stations", "color": "#1e3a8a", "mode": "point", "tags": [("amenity", "police")]},
    "fire_stations": {"label": "Fire Stations", "color": "#b91c1c", "mode": "point", "tags": [("amenity", "fire_station")]},
    "post_offices": {"label": "Post Offices", "color": "#ca8a04", "mode": "point", "tags": [("amenity", "post_office")]},
    "places_of_worship": {"label": "Places of Worship", "color": "#a16207", "mode": "point", "tags": [("amenity", "place_of_worship")]},
    "cinemas": {"label": "Cinemas & Theatres", "color": "#9333ea", "mode": "point", "tags": [("amenity", "cinema|theatre")]},
    "fuel_stations": {"label": "Fuel Stations", "color": "#78350f", "mode": "point", "tags": [("amenity", "fuel")]},
    "ev_charging": {"label": "EV Charging", "color": "#65a30d", "mode": "point", "tags": [("amenity", "charging_station")]},
    "parking": {"label": "Parking", "color": "#64748b", "mode": "point", "tags": [("amenity", "parking")]},
    "bus_stops": {"label": "Bus Stops", "color": "#059669", "mode": "point",
                  "tags": [("highway", "bus_stop"), ("public_transport", "platform")], "require": {"public_transport": ("bus", "yes")}},
    "bus_stations": {"label": "Bus Stations / Terminals", "color": "#047857", "mode": "point", "tags": [("amenity", "bus_station")]},
    "railway_stations": {"label": "Railway Stations", "color": "#334155", "mode": "point",
                         "tags": [("railway", "station|halt")]},
    "metro_stations": {"label": "Metro Stations", "color": "#0f766e", "mode": "point",
                       "tags": [("station", "subway|light_rail|monorail")]},
    "industries": {"label": "Industrial Areas", "color": "#57534e", "mode": "geometry", "tags": [("landuse", "industrial")]},
    "parks": {"label": "Parks & Gardens", "color": "#15803d", "mode": "geometry", "tags": [("leisure", "park|garden")]},
    "water_bodies": {"label": "Water Bodies", "color": "#0284c7", "mode": "geometry", "tags": [("natural", "water")]},
    "waterways": {"label": "Waterways", "color": "#0ea5e9", "mode": "geometry", "tags": [("waterway", "river|stream|canal|drain")]},
    "railways": {"label": "Railway Lines", "color": "#475569", "mode": "geometry", "tags": [("railway", "rail|light_rail|subway")]},
    "buildings": {"label": "Buildings", "color": "#94a3b8", "mode": "geometry", "tags": [("building", None)]},
}

ALIASES = {
    "hospital": "hospitals", "school": "schools", "college": "colleges", "university": "universities",
    "office": "offices", "mall": "malls", "shopping_malls": "malls", "shopping_mall": "malls",
    "market": "markets", "clinic": "clinics", "pharmacy": "pharmacies", "bank": "banks",
    "hotel": "hotels", "restaurant": "restaurants", "park": "parks", "bus_stop": "bus_stops",
    "railway_station": "railway_stations", "metro_station": "metro_stations", "petrol_pumps": "fuel_stations",
    "petrol_pump": "fuel_stations", "fuel": "fuel_stations", "government": "government_offices",
    "police_stations": "police", "temples": "places_of_worship", "worship": "places_of_worship",
    "industrial": "industries", "lakes": "water_bodies", "rivers": "waterways",
}

# Keys whose features are linear/areal by nature → geometry mode for ad-hoc key/value searches.
GEOMETRY_KEYS = {"highway", "railway", "waterway", "landuse", "natural", "building", "boundary", "barrier", "power", "aeroway"}


def normalise_category(name: str) -> str | None:
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in OSM_CATEGORIES:
        return key
    return ALIASES.get(key) or ALIASES.get(key.rstrip("s"))


def overpass_filters(tags: list[tuple[str, str | None]]) -> list[str]:
    out = []
    for k, v in tags:
        if v is None:
            out.append(f'["{k}"]')
        elif "|" in v:
            out.append(f'["{k}"~"^({v})$"]')
        else:
            out.append(f'["{k}"="{v}"]')
    return out
