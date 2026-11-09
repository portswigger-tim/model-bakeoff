import pytest

from snip.config import Settings
from snip.storage import LinkStore, SlugTaken
from snip.validation import GENERATED_SLUG_LEN, SLUG_RE, generate_slug


def test_generated_slug_shape():
    for _ in range(200):
        s = generate_slug()
        assert len(s) == GENERATED_SLUG_LEN and SLUG_RE.fullmatch(s)


def test_store_roundtrip_and_conflict():
    s = LinkStore(":memory:")
    s.create("abc", "https://a.example")
    with pytest.raises(SlugTaken):
        s.create("abc", "https://b.example")
    assert s.visit("abc") == "https://a.example"
    assert s.get("abc").visits == 1
    assert s.visit("zzz") is None
    assert s.delete("abc") and not s.delete("abc")


def test_store_creates_parent_dir(tmp_path):
    LinkStore(str(tmp_path / "nested" / "dir" / "x.db")).close()
    assert (tmp_path / "nested" / "dir" / "x.db").exists()


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SNIP_API_TOKEN", "t")
    monkeypatch.setenv("SNIP_DB_PATH", "/tmp/x.db")
    monkeypatch.setenv("SNIP_BASE_URL", "https://s.example/")
    s = Settings.from_env()
    assert (s.api_token, s.db_path, s.base_url) == ("t", "/tmp/x.db", "https://s.example")
    monkeypatch.delenv("SNIP_API_TOKEN")
    monkeypatch.delenv("SNIP_BASE_URL")
    assert Settings.from_env().api_token is None
