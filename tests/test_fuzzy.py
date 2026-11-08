from app.core.fuzzy import closeness, edit_distance, shakiest_word


def test_edit_distance():
    assert edit_distance("dance", "dace") == 1
    assert edit_distance("dance", "danced") == 1
    assert edit_distance("dance", "disco", cap=2) > 2


def test_shakiest_word_prefers_unknown_short_words():
    known = {"chris", "gooding", "dance"}
    assert shakiest_word("dace it out chris gooding", known) == "dace"
    assert shakiest_word("danced it out chris gooding", known) == "danced"
    assert shakiest_word("chris gooding", known) in ("chris", "gooding")        # nothing unknown: shortest non-common
    assert shakiest_word("volpat", known) is None                               # one word: nothing to drop


def test_closeness_ranks_near_misses_first():
    assert closeness("Chris Gooding - Dance It Out.mp3", "dace") == 0
    assert closeness("Chris Gooding - Get Naked.mp3", "dace") == 1


def test_clean_query_strips_edge_punctuation_only():
    from app.core.service import clean_query
    assert clean_query("ulo s.") == "ulo s"
    assert clean_query("weber, norman") == "weber norman"
    assert clean_query("a.m. drum&bass 7'") == "a.m. drum&bass 7"
    assert clean_query("(remix)") == "remix"
