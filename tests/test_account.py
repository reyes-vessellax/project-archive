"""Local account: sign-up rules, hashed password, sign-in, profile, delete."""
from __future__ import annotations

import pytest

from app.core.account import AccountError, AccountStore


@pytest.fixture
def store(service):
    return AccountStore(service.db)


def test_sign_up_and_in(store):
    a = store.sign_up("Chris Gooding", "Chris@Example.com", "correct horse battery")
    assert a.email == "chris@example.com" and a.initials == "CG" and a.password_hash.startswith("pbkdf2$")
    assert "correct horse" not in a.password_hash
    assert store.sign_in("chris@example.com", "correct horse battery").name == "Chris Gooding"
    with pytest.raises(AccountError):
        store.sign_in("chris@example.com", "wrong password here")


@pytest.mark.parametrize("name,email,pw", [("", "a@b.co", "longenoughpw"), ("A", "not-an-email", "longenoughpw"), ("A", "a@b.co", "short")])
def test_sign_up_validation(store, name, email, pw):
    with pytest.raises(AccountError):
        store.sign_up(name, email, pw)


def test_profile_password_delete(store):
    store.sign_up("Chris Gooding", "c@x.io", "correct horse battery")
    a = store.update_profile("Chris G", "GOODING", "House edits.", "c@x.io")
    assert (a.dj_name, a.bio, a.display_name) == ("GOODING", "House edits.", "GOODING")
    with pytest.raises(AccountError):
        store.change_password("nope nope nope", "another long password")
    store.change_password("correct horse battery", "another long password")
    assert store.sign_in("c@x.io", "another long password")
    store.delete()
    assert store.load() is None


def test_settings_and_account_coexist(service):
    service.accounts.sign_up("A B", "a@b.co", "longenoughpw!")
    s = service.settings; s.theme = "dark"; service.save_settings(s)
    assert service.accounts.load().email == "a@b.co"          # saving settings keeps the account
    from app.config import Settings
    assert Settings.from_dict(service.db.load_settings()).theme == "dark"
