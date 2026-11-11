"""Reyes: "it says 'good', but it's not a good track". A sound file that fails the club checks isn't Good."""
from app.ui import theme as T


def test_not_club_ready_is_never_good():
    club_fail = {"ready": False, "checks": [{"id": "club_mono", "status": "FAIL"}]}
    assert T.grade({"overall_status": "PASS", "club": club_fail}) == "CLUB"
    assert T.grade({"overall_status": "WARN", "club": club_fail}) == "CLUB"
    assert T.grade({"overall_status": "FAIL", "club": club_fail}) == "FAIL"        # broken stays broken
    assert T.grade({"overall_status": "PASS", "club": {"ready": True}}) == "PASS"
    assert T.grade({"overall_status": "PASS"}) == "PASS"                           # older checks: no club part
    assert T.GRADE_WORD["CLUB"] == "No club" and T.TAG_COLOUR["No club"] == "fail"
