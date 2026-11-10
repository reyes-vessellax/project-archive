"""Era crates: hand-picked doors into house music, from the first Chicago 12"s to now, for Discover.

A STARTER SET, written to be edited by people who know the scene (Reyes, Chris). Each crate names the labels
and artists to dig through; Discover looks each one up on MusicBrainz / Discogs when it's opened, so a name
here only has to be spelled the way Discogs spells it. Order within a list = order shown.
"""
from __future__ import annotations

ERAS = [
    {
        "key": "chicago",
        "name": "Chicago jack",
        "years": "1984–1990",
        "blurb": "Drum machines, a warehouse and a Roland TB-303. Where house got its name.",
        "labels": ["Trax Records", "DJ International Records", "Dance Mania", "Bright Star Records"],
        "artists": ["Frankie Knuckles", "Marshall Jefferson", "Larry Heard", "Farley \"Jackmaster\" Funk",
                    "Steve \"Silk\" Hurley", "Ron Hardy", "Jesse Saunders", "Fast Eddie", "Lil Louis", "Adonis"],
    },
    {
        "key": "acid",
        "name": "Acid",
        "years": "1987–1992",
        "blurb": "The 303 squelch, from Phuture's Acid Tracks to the Dutch and UK records that followed.",
        "labels": ["Trax Records", "Djax-Up-Beats", "Warehouse Records"],
        "artists": ["Phuture", "DJ Pierre", "Armando", "Sleezy D", "Bam Bam", "Mike Dunn", "Tyree"],
    },
    {
        "key": "detroit",
        "name": "Detroit deep",
        "years": "1988–2005",
        "blurb": "Soul and machines: from the Belleville three to Moodymann's and Theo Parrish's slow burners.",
        "labels": ["KMS", "Transmat", "Planet E", "KDJ", "Sound Signature", "Mahogani Music", "Metroplex"],
        "artists": ["Kevin Saunderson", "Derrick May", "Carl Craig", "Moodymann", "Theo Parrish", "Rick Wade",
                    "Terrence Parker", "Alton Miller", "Chez Damier"],
    },
    {
        "key": "nyc",
        "name": "New York & Jersey garage",
        "years": "1987–1998",
        "blurb": "Paradise Garage soul: gospel vocals, organ stabs, and the producers who built them.",
        "labels": ["Nu Groove Records", "Strictly Rhythm", "Nervous Records", "King Street Sounds", "Movin' Records",
                   "Henry Street Music", "Emotive Records"],
        "artists": ["Kerri Chandler", "Masters At Work", "Todd Terry", "Kenny Dope", "Louie Vega", "Larry Levan",
                    "Tony Humphries", "Blaze", "Joe Claussell", "Mood II Swing"],
    },
    {
        "key": "ghetto",
        "name": "Ghetto house",
        "years": "1992–2000",
        "blurb": "Dance Mania at full speed: raw, rude and made for the footwork circle.",
        "labels": ["Dance Mania", "Relief Records", "Cajual Records"],
        "artists": ["DJ Funk", "DJ Deeon", "Paul Johnson", "Jammin Gerald", "Parris Mitchell", "DJ Milton",
                    "Cajmere", "Green Velvet"],
    },
    {
        "key": "deep90s",
        "name": "Deep '90s",
        "years": "1992–2000",
        "blurb": "Chicago's second wave of deep: jazz chords, long fades, records built for the last hour.",
        "labels": ["Prescription", "Guidance Recordings", "Large Records", "Cajual Records", "Clairaudience"],
        "artists": ["Ron Trent", "Chez Damier", "Larry Heard", "Glenn Underground", "Anthony Nicholson",
                    "Jerome Sydenham", "Boo Williams"],
    },
    {
        "key": "french",
        "name": "French filter",
        "years": "1996–2002",
        "blurb": "Disco loops through a filter sweep: the Paris sound that took house to the charts.",
        "labels": ["Roulé", "Crydamoure", "Versatile Records", "Yellow Productions"],
        "artists": ["Daft Punk", "Thomas Bangalter", "Alan Braxe", "DJ Falcon", "Cassius", "Motorbass",
                    "Étienne de Crécy", "I:Cube"],
    },
    {
        "key": "disco",
        "name": "Disco roots",
        "years": "1976–1985",
        "blurb": "Before house: the 12\" mixes the Warehouse and the Garage were built on.",
        "labels": ["West End Records", "Salsoul Records", "Prelude Records", "SAM Records"],
        "artists": ["Larry Levan", "Walter Gibbons", "François Kevorkian", "Tom Moulton", "Patrick Adams",
                    "Arthur Russell"],
    },
]


ERAS += [
    {
        "key": "deep00s",
        "name": "Deep & soulful 2000s",
        "years": "2000–2009",
        "blurb": "Detroit soul, Berlin minimal-deep and London's warm side: the decade house went quietly deep.",
        "labels": ["Mahogani Music", "Freerange Records", "Innervisions", "Get Physical Music", "Mojuba", "Moods & Grooves"],
        "artists": ["Omar-S", "Jimpster", "Âme", "Dixon", "Henrik Schwarz", "Osunlade", "Kerri Chandler", "Moodymann"],
    },
    {
        "key": "lofi",
        "name": "Lo-fi & outsider",
        "years": "2010–2018",
        "blurb": "Tape hiss, drum machines through cheap mixers, and a new generation digging the old way.",
        "labels": ["L.I.E.S.", "Lobster Theremin", "Rhythm Section International", "Shall Not Fade", "Local Talk",
                   "Running Back"],
        "artists": ["Legowelt", "DJ Seinfeld", "Ross From Friends", "Palms Trax", "Mall Grab", "Chaos In The CBD",
                    "Kassem Mosse", "Floating Points"],
    },
    {
        "key": "tech",
        "name": "Tech & bass house",
        "years": "2010–now",
        "blurb": "Big rooms, rolling bass and the labels that run the summer festivals.",
        "labels": ["Dirtybird", "Hot Creations", "Toolroom", "Defected", "Solid Grooves Records", "Crosstown Rebels"],
        "artists": ["Claude VonStroke", "Jamie Jones", "Patrick Topping", "Fisher", "MK", "Mark Knight", "Michael Bibi"],
    },
]


def era(key: str) -> dict | None:
    return next((e for e in ERAS if e["key"] == key), None)


# Essential labels for Discover: old and new cornerstones, whatever is in the user's library. (name, city · era)
ESSENTIAL_LABELS = [
    ("Trax Records", "Chicago · 1980s"), ("Strictly Rhythm", "New York · 1990s"), ("KMS", "Detroit · 1980s"),
    ("Dance Mania", "Chicago · 1980s"), ("Nu Groove Records", "New York · 1980s"), ("Prescription", "Chicago · 1990s"),
    ("Relief Records", "Chicago · 1990s"), ("Defected", "London · 1999–"), ("Mahogani Music", "Detroit · 2000s–"),
    ("Freerange Records", "London · 1990s–"), ("Innervisions", "Berlin · 2005–"), ("Classic Music Company", "Chicago/London · 1990s–"),
    ("Dirtybird", "San Francisco · 2005–"), ("L.I.E.S.", "New York · 2010–"), ("Lobster Theremin", "London · 2013–"),
    ("Rhythm Section International", "London · 2014–"),
]


def label_of_the_day(day_ordinal: int) -> str:
    """Today's dig rotates through the essential labels, one a day."""
    return ESSENTIAL_LABELS[day_ordinal % len(ESSENTIAL_LABELS)][0]


# Discover's daily rotation: a wide pool of labels, every era. 8 rows a day (Label of the day + 7), different each day.
LABEL_POOL = [
    # Chicago
    "Trax Records", "DJ International Records", "Dance Mania", "Relief Records", "Cajual Records", "Prescription",
    "Guidance Recordings", "Undaground Therapy Muzik", "Chiwax",
    # New York & New Jersey
    "Strictly Rhythm", "Nu Groove Records", "Nervous Records", "King Street Sounds", "Henry Street Music",
    "Movin' Records", "Emotive Records", "Easy Street Records", "Ibadan Records", "Spiritual Life Music",
    "MAW Records", "Madhouse Records",
    # Detroit
    "KMS", "Transmat", "Planet E", "KDJ", "Sound Signature", "Mahogani Music", "Metroplex", "Moods & Grooves",
    "430 West", "Underground Resistance", "FXHE Records",
    # UK & Europe
    "Defected", "Glitterbox Recordings", "Freerange Records", "Glasgow Underground", "Paper Recordings",
    "Peacefrog Records", "Classic Music Company", "Innervisions", "Get Physical Music", "Mojuba", "Running Back",
    "Dirt Crew Recordings", "Clone Records", "Rush Hour", "Phonica Records",
    # France
    "Roulé", "Crydamoure", "Versatile Records", "Yellow Productions",
    # 2010s and now
    "L.I.E.S.", "Lobster Theremin", "Rhythm Section International", "Shall Not Fade", "Local Talk",
    "Dirtybird", "Hot Creations", "Toolroom", "Solid Grooves Records", "Crosstown Rebels", "Repopulate Mars",
    "Snatch! Records",
    # Disco roots and edits
    "West End Records", "Salsoul Records", "Prelude Records", "Razor-N-Tape",
]

STYLES = ["Deep house", "Acid house", "Chicago house", "Garage house", "Disco edit", "Tech house"]


def todays_labels(day_ordinal: int, n: int = 8) -> list[str]:
    """n labels for today: a different slice of the pool each day, so the page changes daily."""
    import random
    pool = list(LABEL_POOL)
    random.Random(day_ordinal).shuffle(pool)
    return pool[:n]


# Discover's genre pills: each fills the page with its labels' rows and its style rows (phrases searched as written).
GENRES = [
    {"key": "deep", "name": "Deep", "dot": "#2f6fed", "styles": ["Deep house"],
     "labels": ["Prescription", "Guidance Recordings", "Mahogani Music", "Freerange Records", "Sound Signature",
                "Moods & Grooves", "Large Records"]},
    {"key": "chicago", "name": "Chicago", "dot": "#dc143c", "styles": ["Chicago house", "Jackin house"],
     "labels": ["Trax Records", "DJ International Records", "Dance Mania", "Relief Records", "Cajual Records", "Chiwax"]},
    {"key": "detroit", "name": "Detroit", "dot": "#7a7a7a", "styles": ["Detroit house"],
     "labels": ["KMS", "Transmat", "Planet E", "KDJ", "Metroplex", "Underground Resistance", "FXHE Records"]},
    {"key": "garage", "name": "Garage & NY", "dot": "#9b51e0", "styles": ["Garage house"],
     "labels": ["Nu Groove Records", "Strictly Rhythm", "King Street Sounds", "Nervous Records", "Henry Street Music",
                "Movin' Records"]},
    {"key": "soulful", "name": "Soulful", "dot": "#f2994a", "styles": ["Soulful house"],
     "labels": ["Defected", "King Street Sounds", "Spiritual Life Music", "Ibadan Records", "Glitterbox Recordings"]},
    {"key": "disco", "name": "Disco & edits", "dot": "#ff4fa3", "styles": ["Disco edit", "Nu disco"],
     "labels": ["Salsoul Records", "West End Records", "Prelude Records", "Glitterbox Recordings", "Razor-N-Tape"]},
    {"key": "acid", "name": "Acid", "dot": "#b5e61d", "styles": ["Acid house"],
     "labels": ["Trax Records", "Djax-Up-Beats", "Warehouse Records"]},
    {"key": "ghetto", "name": "Ghetto & juke", "dot": "#ff6b2c", "styles": ["Ghetto house", "Juke"],
     "labels": ["Dance Mania", "Relief Records"]},
    {"key": "tech", "name": "Tech house", "dot": "#00b3a4", "styles": ["Tech house"],
     "labels": ["Dirtybird", "Hot Creations", "Toolroom", "Solid Grooves Records", "Repopulate Mars", "Snatch! Records"]},
    {"key": "lofi", "name": "Lo-fi", "dot": "#a1887f", "styles": ["Lo-fi house", "Outsider house"],
     "labels": ["L.I.E.S.", "Lobster Theremin", "Shall Not Fade", "Rhythm Section International", "Local Talk"]},
    {"key": "french", "name": "French filter", "dot": "#3b82f6", "styles": ["French house", "Filter house"],
     "labels": ["Roulé", "Crydamoure", "Versatile Records", "Yellow Productions"]},
    {"key": "minimal", "name": "Minimal", "dot": "#9e9e9e", "styles": ["Minimal house", "Microhouse"],
     "labels": ["Perlon", "Mojuba"]},
    {"key": "afro", "name": "Afro house", "dot": "#f4b400", "styles": ["Afro house"], "labels": []},
    {"key": "italo", "name": "Italo & cosmic", "dot": "#e040fb", "styles": ["Italo disco", "Cosmic disco"], "labels": []},
    {"key": "balearic", "name": "Balearic", "dot": "#26c6da", "styles": ["Balearic"], "labels": ["Running Back"]},
]


def genre(key: str) -> dict | None:
    return next((g for g in GENRES if g["key"] == key), None)
