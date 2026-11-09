import re

import pytest

from .conftest import AUTH

URL = "https://example.com/some/path?q=1"


def create(client, **body):
    return client.post("/api/links", json=body, headers=AUTH)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200


def test_create_generated_slug(client):
    r = create(client, url=URL)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"slug", "url", "short_url", "created_at"}
    assert body["url"] == URL
    assert re.fullmatch(r"[A-Za-z0-9]{8}", body["slug"])
    assert body["short_url"] == f"http://testserver/{body['slug']}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", body["created_at"])


def test_generated_slugs_are_distinct(client):
    slugs = {create(client, url=URL).json()["slug"] for _ in range(50)}
    assert len(slugs) == 50


def test_generated_slug_retries_on_collision(client, monkeypatch):
    create(client, url=URL, slug="taken-one")
    seq = iter(["taken-one", "fresh-one"])
    monkeypatch.setattr("snip.app.generate_slug", lambda: next(seq))
    r = create(client, url=URL)
    assert r.status_code == 201
    assert r.json()["slug"] == "fresh-one"


def test_custom_slug_and_base_url(make_client):
    c = make_client(base_url="https://sn.ip/")
    r = create(c, url=URL, slug="my_Slug-1")
    assert r.status_code == 201
    assert r.json()["slug"] == "my_Slug-1"
    assert r.json()["short_url"] == "https://sn.ip/my_Slug-1"


def test_taken_slug_conflicts(client):
    assert create(client, url=URL, slug="abc").status_code == 201
    r = create(client, url="https://other.example", slug="abc")
    assert r.status_code == 409
    assert "error" in r.json()
    assert client.get("/api/links/abc").json()["url"] == URL


@pytest.mark.parametrize("slug", ["ab", "a" * 33, "has space", "bad/slug", "dötted", "a.b", "", 123, ["abc"], "api", "HEALTHZ"])
def test_invalid_slug(client, slug):
    r = create(client, url=URL, slug=slug)
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        123,
        "example.com",
        "/relative/path",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "data:text/html,hi",
        "file:///etc/passwd",
        "http://",
        "https:///nohost",
        "http://exa mple.com",
        "http://example.com/\r\nSet-Cookie: x=1",
        " https://example.com",
        "http://example.com:notaport/",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_invalid_url(client, url):
    r = create(client, url=url)
    assert r.status_code == 400
    assert "error" in r.json()


def test_url_length_boundary(client):
    url = "https://example.com/" + "a" * (2048 - len("https://example.com/"))
    assert len(url) == 2048
    assert create(client, url=url).status_code == 201


def test_http_scheme_accepted_case_insensitive(client):
    assert create(client, url="HTTP://example.com").status_code == 201


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'"str"', b"null", b""])
def test_malformed_body(client, raw):
    r = client.post("/api/links", content=raw, headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.json()


def test_oversized_body(client):
    r = client.post("/api/links", content=b'{"url":"' + b"a" * 20000 + b'"}', headers=AUTH)
    assert r.status_code == 400


def test_redirect_counts_visits(client):
    slug = create(client, url=URL).json()["slug"]
    for _ in range(3):
        r = client.get(f"/{slug}")
        assert r.status_code == 302
        assert r.headers["location"] == URL
    meta = client.get(f"/api/links/{slug}")
    assert meta.status_code == 200
    body = meta.json()
    assert body["visits"] == 3
    assert body["url"] == URL and body["slug"] == slug
    assert {"short_url", "created_at"} <= set(body)


def test_metadata_does_not_count_visit(client):
    slug = create(client, url=URL).json()["slug"]
    client.get(f"/api/links/{slug}")
    assert client.get(f"/api/links/{slug}").json()["visits"] == 0


def test_unknown_slug(client):
    assert client.get("/nope123").status_code == 404
    assert client.get("/api/links/nope123").status_code == 404
    assert client.get("/nope123").json() == {"error": "link not found"}


def test_delete(client):
    slug = create(client, url=URL).json()["slug"]
    assert client.delete(f"/api/links/{slug}", headers=AUTH).status_code == 204
    assert client.get(f"/{slug}").status_code == 404
    assert client.get(f"/api/links/{slug}").status_code == 404
    assert client.delete(f"/api/links/{slug}", headers=AUTH).status_code == 404
    # slug can be reused after deletion
    assert create(client, url=URL, slug=slug).status_code == 201


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "test-token"},
        {"Authorization": "Basic test-token"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer test-token-extra"},
    ],
)
def test_writes_require_token(client, headers):
    assert client.post("/api/links", json={"url": URL}, headers=headers).status_code == 401
    slug = create(client, url=URL).json()["slug"]
    r = client.delete(f"/api/links/{slug}", headers=headers)
    assert r.status_code == 401
    assert r.json() == {"error": "missing or invalid bearer token"}
    assert client.get(f"/api/links/{slug}").status_code == 200  # not deleted


def test_auth_checked_before_validation(client):
    assert client.post("/api/links", json={"url": "bad"}).status_code == 401


def test_reads_need_no_token(client):
    slug = create(client, url=URL).json()["slug"]
    assert client.get(f"/{slug}").status_code == 302
    assert client.get(f"/api/links/{slug}").status_code == 200


@pytest.mark.parametrize("token", [None, ""])
def test_unset_token_rejects_all_writes(make_client, token):
    c = make_client(token=token)
    assert c.post("/api/links", json={"url": URL}).status_code == 401
    assert c.post("/api/links", json={"url": URL}, headers={"Authorization": "Bearer "}).status_code == 401
    assert c.post("/api/links", json={"url": URL}, headers={"Authorization": "Bearer x"}).status_code == 401


def test_persists_across_restart(make_client):
    c1 = make_client()
    slug = create(c1, url=URL).json()["slug"]
    c1.get(f"/{slug}")
    c1.__exit__(None, None, None)

    c2 = make_client()
    r = c2.get(f"/{slug}")
    assert r.status_code == 302 and r.headers["location"] == URL
    assert c2.get(f"/api/links/{slug}").json()["visits"] == 2


def test_method_not_allowed_is_json(client):
    r = client.put("/api/links")
    assert r.status_code == 405
    assert "error" in r.json()
