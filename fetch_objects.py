"""
Script to fetch astronomy objects from DBpedia and append to astronomy_kg.ttl.
Run while online; everything works offline after that.
Safe to re-run — it only appends, so run with a fresh OBJECTS list each time
to avoid duplicating triples already in the file.
"""

from SPARQLWrapper import SPARQLWrapper, JSON
import time

ENDPOINT = "https://dbpedia.org/sparql"

# Objects already fetched in the first run — DO NOT re-fetch (would duplicate triples)
OBJECTS_ALREADY_FETCHED = [
    "Sun", "Proxima_Centauri", "Betelgeuse", "Sirius", "Vega",
    "Rigel", "Polaris", "Alpha_Centauri",
    "Mercury_(planet)", "Venus", "Earth", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune",
    "Pluto", "Moon", "Ceres_(dwarf_planet)", "Europa_(moon)",
    "Milky_Way", "Andromeda_Galaxy", "Triangulum_Galaxy",
    "Large_Magellanic_Cloud", "Small_Magellanic_Cloud",
    "Orion_Nebula", "Crab_Nebula", "Eagle_Nebula",
    "Black_hole", "Neutron_star", "White_dwarf",
    "Supernova", "Quasar", "Pulsar",
    "International_Space_Station", "Hubble_Space_Telescope",
    "James_Webb_Space_Telescope",
]

# Batch 2 — already fetched successfully, do not re-fetch
OBJECTS_ALREADY_FETCHED_BATCH2 = [
    "Arcturus", "Aldebaran", "Antares", "Spica", "Deneb", "Canopus",
    "Fomalhaut", "Achernar",
    "Ring_Nebula", "Helix_Nebula", "Lagoon_Nebula", "Trifid_Nebula",
    "Whirlpool_Galaxy", "Sombrero_Galaxy", "Pinwheel_Galaxy",
    "Sculptor_Galaxy", "Centaurus_A",
    "Ursa_Major", "Scorpius",
    "Asteroid", "Exoplanet",
]

# Batch 3 — already fetched (moons + constellations with parenthesised names)
OBJECTS_ALREADY_FETCHED_BATCH3 = [
    "Titan_(moon)", "Io_(moon)", "Ganymede_(moon)", "Callisto_(moon)",
    "Enceladus_(moon)", "Triton_(moon)", "Oberon_(moon)", "Titania_(moon)",
    "Orion_(constellation)", "Cassiopeia_(constellation)", "Leo_(constellation)",
]

# Batch 4 — effectiveTemperature, dbp:mass/radius
OBJECTS_ALREADY_FETCHED_BATCH4 = [
    "Sun", "Mercury_(planet)", "Venus", "Earth", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune",
    "Betelgeuse", "Sirius", "Vega", "Rigel", "Polaris",
    "Arcturus", "Aldebaran", "Antares", "Proxima_Centauri",
]

# Batch 5 — discovery, constellation/location, chemical composition
OBJECTS = [
    # Planets discovered (not known in antiquity)
    "Uranus", "Neptune", "Pluto", "Ceres_(dwarf_planet)",
    # All moons — discoverers well-documented in DBpedia
    "Europa_(moon)", "Titan_(moon)", "Ganymede_(moon)", "Callisto_(moon)",
    "Io_(moon)", "Enceladus_(moon)", "Triton_(moon)", "Oberon_(moon)", "Titania_(moon)",
    # Stars — need constellation
    "Betelgeuse", "Sirius", "Vega", "Rigel", "Polaris", "Arcturus",
    "Aldebaran", "Antares", "Proxima_Centauri", "Fomalhaut", "Achernar",
    "Spica", "Deneb", "Canopus",
    # Nebulae — need constellation location + discoverers
    "Orion_Nebula", "Crab_Nebula", "Eagle_Nebula", "Ring_Nebula",
    "Helix_Nebula", "Lagoon_Nebula", "Trifid_Nebula",
    # Galaxies — have discoverers
    "Andromeda_Galaxy", "Triangulum_Galaxy", "Whirlpool_Galaxy",
    "Sombrero_Galaxy", "Pinwheel_Galaxy", "Sculptor_Galaxy", "Centaurus_A",
    # Gas giants + Sun — chemical composition
    "Sun", "Jupiter", "Saturn", "Uranus", "Neptune",
    # Inner planets for completeness
    "Mercury_(planet)", "Venus", "Earth", "Mars",
]

# Deduplicate while preserving order
seen = set()
OBJECTS = [x for x in OBJECTS if not (x in seen or seen.add(x))]

PREDICATES = [
    "dbo:discoverer",
    "dbo:discoveryDate",
    "dbp:discoverer",
    "dbo:constellation",
    "dbp:constellation",
    "dbo:hasChemicalElement",
]

PREFIXES = """
    PREFIX dbo:  <http://dbpedia.org/ontology/>
    PREFIX dbp:  <http://dbpedia.org/property/>
    PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

def fetch_object(sparql, name):
    """Fetch all wanted predicates for one object. Returns list of (p, o) pairs."""
    pred_filter = " || ".join([f"?p = {pred}" for pred in PREDICATES])
    query = f"""
    {PREFIXES}
    SELECT ?p ?o WHERE {{
        <http://dbpedia.org/resource/{name}> ?p ?o .
        FILTER ({pred_filter})
        FILTER (lang(?o) = 'en' || !isLiteral(?o) || datatype(?o) != <http://www.w3.org/2001/XMLSchema#string>)
    }}
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        results = sparql.query().convert()
        return results["results"]["bindings"]
    except Exception as e:
        print(f"  ERROR fetching {name}: {e}")
        return []


def to_ttl_object(val):
    """Convert a SPARQL result value dict to a Turtle-format string."""
    vtype = val["type"]
    v = val["value"]
    if vtype == "uri":
        return f"<{v}>"
    elif vtype == "literal":
        lang = val.get("xml:lang", "")
        dtype = val.get("datatype", "")
        escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        if lang:
            return f'"{escaped}"@{lang}'
        elif dtype:
            return f'"{escaped}"^^<{dtype}>'
        else:
            return f'"{escaped}"'
    return None


def main():
    sparql = SPARQLWrapper(ENDPOINT)
    sparql.setTimeout(30)

    subject_base = "http://dbpedia.org/resource/"
    new_triples = []

    for name in OBJECTS:
        print(f"Fetching {name}...", end=" ")
        rows = fetch_object(sparql, name)
        count = 0
        for row in rows:
            obj_str = to_ttl_object(row["o"])
            if obj_str is None:
                continue
            triple = f"<{subject_base}{name}> <{row['p']['value']}> {obj_str} ."
            new_triples.append(triple)
            count += 1
        print(f"{count} triples")
        time.sleep(0.3)   # be polite to the public endpoint

    # Append to the existing TTL file
    output_path = "astronomy_kg.ttl"
    with open(output_path, "a", encoding="utf-8") as f:
        f.write("\n# --- Batch 5: discovery, constellation, composition ---\n")
        for triple in new_triples:
            f.write(triple + "\n")

    print(f"\nDone. Added {len(new_triples)} triples to {output_path}")
    print("Move the OBJECTS list to OBJECTS_ALREADY_FETCHED_BATCH5 before the next run.")


if __name__ == "__main__":
    main()
