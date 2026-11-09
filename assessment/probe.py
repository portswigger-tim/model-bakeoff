#!/usr/bin/env python3
"""Black-box conformance probe for a running "snip" service (see BRIEF.md).

Every solution is driven by exactly the same requests, so the results are
comparable. Usage:

    probe.py BASE_URL TOKEN phase1 STATE_FILE   # fresh server
    probe.py BASE_URL TOKEN phase2 STATE_FILE   # same data dir, after restart

Prints one JSON object per check: {"id", "ok", "detail"}.
"""
import concurrent.futures
import http.client
import json
import sys
import urllib.parse

BASE, TOKEN, PHASE, STATE = sys.argv[1:5]
u = urllib.parse.urlparse(BASE)
results = []


def req(method, path, body=None, token=TOKEN, raw=None, headers=None):
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    h = dict(headers or {})
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    try:
        try:
            conn.request(method, path, body=data, headers=h)
        except (BrokenPipeError, ConnectionResetError):
            pass  # server answered early (e.g. 413) and closed; read what it sent
        r = conn.getresponse()
        payload = r.read()
        try:
            js = json.loads(payload) if payload else None
        except ValueError:
            js = None
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), js
    except Exception as e:  # connection reset etc.
        return 0, {}, {"exception": repr(e)}
    finally:
        conn.close()


def check(cid, ok, detail=""):
    results.append({"id": cid, "ok": bool(ok), "detail": str(detail)[:200]})


def is_json_error(status, headers, js, want):
    return status == want and "json" in headers.get("content-type", "") and isinstance(js, dict)


if PHASE == "phase1":
    s, h, j = req("GET", "/healthz", token=None)
    check("healthz_200", s == 200, s)

    s, h, j = req("POST", "/api/links", {"url": "https://example.com/a"}, token=None)
    check("post_no_auth_401", is_json_error(s, h, j, 401), s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/a"}, token="wrong-token-wrong-token-wrong")
    check("post_bad_token_401", s == 401, s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/a"}, token=None,
                  headers={"Authorization": f"Basic {TOKEN}"})
    check("post_non_bearer_401", s == 401, s)

    s, h, j = req("POST", "/api/links", {"url": "https://example.com/generated?q=1#frag"})
    gen = (j or {}).get("slug") if isinstance(j, dict) else None
    keys_ok = isinstance(j, dict) and all(k in j for k in ("slug", "url", "short_url", "created_at"))
    check("create_generated_201", s == 201 and keys_ok, f"{s} {j}")
    check("generated_slug_charset_len", bool(gen) and len(gen) >= 6
          and all(c.isalnum() or c in "-_" for c in gen), gen)
    check("short_url_ends_with_slug", isinstance(j, dict) and str(j.get("short_url", "")).endswith("/" + str(gen)),
          (j or {}).get("short_url") if isinstance(j, dict) else j)

    gens = set()
    for _ in range(25):
        s2, _, j2 = req("POST", "/api/links", {"url": "https://example.com/many"})
        if s2 == 201:
            gens.add(j2.get("slug"))
    check("generated_slugs_unique", len(gens) == 25, len(gens))

    s, h, j = req("POST", "/api/links", {"url": "https://example.com/custom", "slug": "My_custom-1"})
    check("create_custom_201", s == 201 and isinstance(j, dict) and j.get("slug") == "My_custom-1", f"{s} {j}")
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/other", "slug": "My_custom-1"})
    check("duplicate_slug_409", s == 409, s)

    bad_urls = {
        "javascript_scheme": "javascript:alert(1)",
        "data_scheme": "data:text/html,<script>alert(1)</script>",
        "ftp_scheme": "ftp://example.com/x",
        "relative_url": "/just/a/path",
        "no_host": "http://",
        "crlf_injection": "https://example.com/\r\nSet-Cookie: pwn=1",
        "too_long_2049": "https://example.com/" + "a" * (2049 - len("https://example.com/")),
        "empty": "",
    }
    for name, url in bad_urls.items():
        s, h, j = req("POST", "/api/links", {"url": url})
        check(f"reject_{name}_400", is_json_error(s, h, j, 400), s)
    for name, val in {"url_not_string": 123, "url_null": None}.items():
        s, h, j = req("POST", "/api/links", {"url": val})
        check(f"reject_{name}_400", s == 400, s)
    s, h, j = req("POST", "/api/links", {})
    check("reject_missing_url_400", s == 400, s)
    s, h, j = req("POST", "/api/links", raw=b"{not json")
    check("reject_malformed_json_400", is_json_error(s, h, j, 400), s)
    s, h, j = req("POST", "/api/links", raw=b'["https://example.com"]')
    check("reject_json_array_400", s == 400, s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/" + "a" * (2048 - len("https://example.com/"))})
    check("accept_exactly_2048_201", s == 201, s)
    s, h, j = req("POST", "/api/links", {"url": "HTTPS://EXAMPLE.COM/upper"})
    check("accept_uppercase_scheme_201", s == 201, s)

    bad_slugs = {"too_short": "ab", "too_long": "a" * 33, "dot": "a.bc", "slash": "abc/def",
                 "space": "abc def", "unicode": "caféx", "encoded": "abc%2F"}
    for name, slug in bad_slugs.items():
        s, h, j = req("POST", "/api/links", {"url": "https://example.com/s", "slug": slug})
        check(f"reject_slug_{name}_400", s == 400, s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/s", "slug": "abc"})
    check("accept_slug_len3_201", s == 201, s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/s", "slug": "b" * 32})
    check("accept_slug_len32_201", s == 201, s)
    s, h, j = req("POST", "/api/links", {"url": "https://example.com/s", "slug": 42})
    check("reject_slug_not_string_400", s == 400, s)

    s, h, j = req("POST", "/api/links", raw=b'{"url":"https://example.com/' + b"a" * 2_000_000 + b'"}')
    check("huge_body_4xx_not_5xx", 400 <= s < 500, s)

    s, h, j = req("GET", "/My_custom-1", token=None)
    check("redirect_302_location", s == 302 and h.get("location") == "https://example.com/custom", f"{s} {h.get('location')}")
    req("GET", "/My_custom-1", token=None)
    s, h, j = req("GET", "/api/links/My_custom-1", token=None)
    check("metadata_visits_2", s == 200 and isinstance(j, dict) and j.get("visits") == 2, f"{s} {j}")
    check("metadata_fields", isinstance(j, dict) and all(k in j for k in ("slug", "url", "short_url", "created_at", "visits")), j)

    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        list(ex.map(lambda _: req("GET", "/My_custom-1", token=None), range(30)))
    s, h, j = req("GET", "/api/links/My_custom-1", token=None)
    check("concurrent_visits_32", isinstance(j, dict) and j.get("visits") == 32, (j or {}).get("visits") if isinstance(j, dict) else j)

    s, h, j = req("GET", "/nope-nope-nope", token=None)
    check("redirect_unknown_404", s == 404, s)
    s, h, j = req("GET", "/api/links/nope-nope-nope", token=None)
    check("metadata_unknown_404_json", is_json_error(s, h, j, 404), s)

    s, h, j = req("DELETE", "/api/links/abc", token=None)
    check("delete_no_auth_401", s == 401, s)
    s, h, j = req("GET", "/abc", token=None)
    check("delete_no_auth_did_not_delete", s == 302, s)
    s, h, j = req("DELETE", "/api/links/abc")
    check("delete_2xx", 200 <= s < 300, s)
    s, h, j = req("GET", "/abc", token=None)
    check("deleted_redirect_404", s == 404, s)
    s, h, j = req("DELETE", "/api/links/abc")
    check("delete_unknown_404", s == 404, s)

    # Reserved-path collisions: can a custom slug shadow the API or health check?
    s, h, j = req("POST", "/api/links", {"url": "https://evil.example/", "slug": "healthz"})
    s2, _, _ = req("GET", "/healthz", token=None)
    check("healthz_not_shadowed", s2 == 200, f"create={s} healthz={s2}")

    json.dump({"custom": "My_custom-1", "gen": gen}, open(STATE, "w"))
else:
    st = json.load(open(STATE))
    s, h, j = req("GET", f"/api/links/{st['custom']}", token=None)
    check("persist_custom_after_restart", s == 200 and isinstance(j, dict) and j.get("visits") == 32, f"{s} {j}")
    s, h, j = req("GET", f"/{st['gen']}", token=None)
    check("persist_generated_after_restart", s == 302, s)
    s, h, j = req("GET", "/abc", token=None)
    check("delete_persisted_after_restart", s == 404, s)

for r in results:
    print(json.dumps(r))
