"""A little give for search: which word to drop when nothing matches, and how close a result is to what
was typed. Nothing here talks to the network; the window decides when to use it."""
from __future__ import annotations

import re

# Words that are almost never the typo: common in track names, or too short to be the problem.
COMMON = set("""
a an the of and to in on it out up my your is for with feat ft vs mix remix edit dub extended original club radio
version vocal instrumental live acoustic deep tech house techno trance drum bass dnb garage disco funk soul jazz
love night day life time dance feel good bad come go stay away back home free run move body baby girl boy man
""".split())

_word = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return _word.findall(text.lower())


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein with an early exit once the distance can't stay under cap."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v); best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def shakiest_word(query: str, known: set[str]) -> str | None:
    """The word most likely to be the mistake: not a common word, not seen in any result or library name
    before, and among those the shortest (short words are the easiest to mistype and the least useful)."""
    ws = words(query)
    if len(ws) < 2:
        return None
    unknown = [w for w in ws if w not in COMMON and w not in known]
    pool = unknown or [w for w in ws if w not in COMMON] or ws
    return min(pool, key=lambda w: (len(w), ws.index(w)))


def closeness(name: str, dropped: str) -> int:
    """0 = the dropped word appears in the name within a typo or two; 1 = it doesn't."""
    if not dropped:
        return 1
    tol = 1 if len(dropped) <= 4 else 2
    for w in words(name):
        if abs(len(w) - len(dropped)) <= tol and edit_distance(w, dropped, tol) <= tol:
            return 0
    return 1
