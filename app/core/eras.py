"""Era crates: hand-picked doors into the history of house, for Discover.

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


def era(key: str) -> dict | None:
    return next((e for e in ERAS if e["key"] == key), None)


# Essential labels for Discover: the cornerstones, whatever is in the user's library. (name as Discogs spells it, city)
ESSENTIAL_LABELS = [
    ("Trax Records", "Chicago"), ("DJ International Records", "Chicago"), ("Dance Mania", "Chicago"),
    ("Strictly Rhythm", "New York"), ("Nu Groove Records", "New York"), ("Nervous Records", "New York"),
    ("KMS", "Detroit"), ("Transmat", "Detroit"), ("Prescription", "Chicago"), ("Relief Records", "Chicago"),
    ("Cajual Records", "Chicago"), ("Henry Street Music", "New York"),
]


def label_of_the_day(day_ordinal: int) -> str:
    """Today's dig rotates through the essential labels, one a day."""
    return ESSENTIAL_LABELS[day_ordinal % len(ESSENTIAL_LABELS)][0]
