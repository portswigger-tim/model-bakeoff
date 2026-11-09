package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"snip/internal/store"
)

const testToken = "test-token-0123456789"

var fixedNow = time.Date(2026, 11, 9, 12, 0, 0, 0, time.UTC)

type testEnv struct {
	t      *testing.T
	srv    *Server
	store  *store.Store
	dbPath string
}

func newEnv(t *testing.T, mod ...func(*Config)) *testEnv {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "snip.db")
	st, err := store.Open(context.Background(), dbPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	cfg := Config{APIToken: testToken, BaseURL: "https://sn.ip/", Now: func() time.Time { return fixedNow }}
	for _, m := range mod {
		m(&cfg)
	}
	return &testEnv{t: t, srv: New(st, cfg), store: st, dbPath: dbPath}
}

func (e *testEnv) do(method, path, body string, hdr map[string]string) *httptest.ResponseRecorder {
	e.t.Helper()
	var req *http.Request
	if body != "" {
		req = httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
	} else {
		req = httptest.NewRequest(method, path, nil)
	}
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	return rec
}

var auth = map[string]string{"Authorization": "Bearer " + testToken}

func (e *testEnv) create(body string) *httptest.ResponseRecorder {
	e.t.Helper()
	return e.do(http.MethodPost, "/api/links", body, auth)
}

func decode[T any](t *testing.T, rec *httptest.ResponseRecorder) T {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("Content-Type = %q, want application/json", ct)
	}
	var v T
	if err := json.Unmarshal(rec.Body.Bytes(), &v); err != nil {
		t.Fatalf("decode %q: %v", rec.Body.String(), err)
	}
	return v
}

func wantStatus(t *testing.T, rec *httptest.ResponseRecorder, want int) {
	t.Helper()
	if rec.Code != want {
		t.Fatalf("status = %d, want %d; body: %s", rec.Code, want, rec.Body.String())
	}
}

func wantJSONError(t *testing.T, rec *httptest.ResponseRecorder, want int) {
	t.Helper()
	wantStatus(t, rec, want)
	body := decode[map[string]string](t, rec)
	if body["error"] == "" {
		t.Fatalf("expected non-empty error message, got %v", body)
	}
}

func TestHealthz(t *testing.T) {
	e := newEnv(t)
	rec := e.do(http.MethodGet, "/healthz", "", nil)
	wantStatus(t, rec, http.StatusOK)
	if body := decode[map[string]string](t, rec); body["status"] != "ok" {
		t.Fatalf("unexpected body %v", body)
	}
}

func TestHealthzReportsStorageFailure(t *testing.T) {
	e := newEnv(t)
	e.store.Close()
	wantJSONError(t, e.do(http.MethodGet, "/healthz", "", nil), http.StatusServiceUnavailable)
}

func TestCreateWithCustomSlug(t *testing.T) {
	e := newEnv(t)
	rec := e.create(`{"url":"https://example.com/a?b=c#d","slug":"my-Link_1"}`)
	wantStatus(t, rec, http.StatusCreated)
	body := decode[map[string]any](t, rec)
	want := map[string]any{
		"slug":       "my-Link_1",
		"url":        "https://example.com/a?b=c#d",
		"short_url":  "https://sn.ip/my-Link_1",
		"created_at": "2026-11-09T12:00:00Z",
	}
	for k, v := range want {
		if body[k] != v {
			t.Errorf("%s = %v, want %v", k, body[k], v)
		}
	}
	if len(body) != len(want) {
		t.Errorf("unexpected fields in %v", body)
	}
	if loc := rec.Header().Get("Location"); loc != "/api/links/my-Link_1" {
		t.Errorf("Location = %q", loc)
	}
}

func TestCreateGeneratesSlug(t *testing.T) {
	e := newEnv(t)
	seen := map[string]bool{}
	for range 20 {
		rec := e.create(`{"url":"http://example.com"}`)
		wantStatus(t, rec, http.StatusCreated)
		body := decode[map[string]string](t, rec)
		slug := body["slug"]
		if !regexp.MustCompile(`^[A-Za-z0-9]{10}$`).MatchString(slug) {
			t.Fatalf("generated slug %q has unexpected shape", slug)
		}
		if seen[slug] {
			t.Fatalf("duplicate generated slug %q", slug)
		}
		seen[slug] = true
		if body["short_url"] != "https://sn.ip/"+slug {
			t.Fatalf("short_url = %q", body["short_url"])
		}
	}
	// An explicit empty slug or null means "generate one".
	wantStatus(t, e.create(`{"url":"http://example.com","slug":""}`), http.StatusCreated)
	wantStatus(t, e.create(`{"url":"http://example.com","slug":null}`), http.StatusCreated)
}

func TestGeneratedSlugCollisionRetries(t *testing.T) {
	slugs := []string{"taken1", "taken1", "fresh1"}
	var mu sync.Mutex
	e := newEnv(t, func(c *Config) {
		c.NewSlug = func() (string, error) {
			mu.Lock()
			defer mu.Unlock()
			s := slugs[0]
			slugs = slugs[1:]
			return s, nil
		}
	})
	wantStatus(t, e.create(`{"url":"https://a.example"}`), http.StatusCreated)
	rec := e.create(`{"url":"https://b.example"}`)
	wantStatus(t, rec, http.StatusCreated)
	if got := decode[map[string]string](t, rec)["slug"]; got != "fresh1" {
		t.Fatalf("slug = %q, want fresh1 after collision", got)
	}
}

func TestGeneratedSlugGivesUpAfterRepeatedCollisions(t *testing.T) {
	e := newEnv(t, func(c *Config) {
		c.NewSlug = func() (string, error) { return "always", nil }
	})
	wantStatus(t, e.create(`{"url":"https://a.example"}`), http.StatusCreated)
	wantJSONError(t, e.create(`{"url":"https://a.example"}`), http.StatusInternalServerError)
}

func TestRandomSlug(t *testing.T) {
	seen := map[string]bool{}
	for range 1000 {
		s, err := randomSlug()
		if err != nil {
			t.Fatal(err)
		}
		if len(s) != generatedSlugLen || validateSlug(s) != nil {
			t.Fatalf("bad slug %q", s)
		}
		if strings.ContainsAny(s, "0O1lI") {
			t.Fatalf("slug %q contains a look-alike character", s)
		}
		if seen[s] {
			t.Fatalf("duplicate slug %q", s)
		}
		seen[s] = true
	}
}

func TestCreateDuplicateSlugConflicts(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"dupe"}`), http.StatusCreated)
	wantJSONError(t, e.create(`{"url":"https://other.example","slug":"dupe"}`), http.StatusConflict)
}

func TestCreateValidation(t *testing.T) {
	long := "https://example.com/" + strings.Repeat("a", 2048-len("https://example.com/"))
	if len(long) != 2048 {
		t.Fatal("bad fixture")
	}
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"`+long+`"}`), http.StatusCreated)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"abc"}`), http.StatusCreated)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"`+strings.Repeat("x", 32)+`"}`), http.StatusCreated)
	wantStatus(t, e.create(`{"url":"HTTPS://EXAMPLE.COM/"}`), http.StatusCreated)

	cases := map[string]string{
		"missing url":         `{}`,
		"empty url":           `{"url":""}`,
		"relative url":        `{"url":"/foo"}`,
		"scheme-relative url": `{"url":"//example.com"}`,
		"ftp url":             `{"url":"ftp://example.com"}`,
		"javascript url":      `{"url":"javascript:alert(1)"}`,
		"data url":            `{"url":"data:text/html,hi"}`,
		"no host":             `{"url":"http://"}`,
		"opaque http":         `{"url":"http:example.com"}`,
		"credentials":         `{"url":"https://user:pass@example.com"}`,
		"whitespace":          `{"url":"https://exa mple.com"}`,
		"newline":             `{"url":"https://example.com/\nX"}`,
		"too long url":        `{"url":"` + long + `a"}`,
		"slug too short":      `{"url":"https://example.com","slug":"ab"}`,
		"slug too long":       `{"url":"https://example.com","slug":"` + strings.Repeat("x", 33) + `"}`,
		"slug bad chars":      `{"url":"https://example.com","slug":"no/slash"}`,
		"slug dot":            `{"url":"https://example.com","slug":"a.b.c"}`,
		"slug unicode":        `{"url":"https://example.com","slug":"héllo"}`,
		"slug reserved":       `{"url":"https://example.com","slug":"healthz"}`,
		"slug reserved case":  `{"url":"https://example.com","slug":"API"}`,
		"url not string":      `{"url":123}`,
		"slug not string":     `{"url":"https://example.com","slug":5}`,
		"unknown field":       `{"url":"https://example.com","extra":1}`,
		"array body":          `[]`,
		"malformed json":      `{"url":`,
		"trailing data":       `{"url":"https://example.com"} {}`,
		"empty body":          ``,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/links", strings.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Authorization", "Bearer "+testToken)
			rec := httptest.NewRecorder()
			e.srv.ServeHTTP(rec, req)
			wantJSONError(t, rec, http.StatusBadRequest)
		})
	}
}

func TestCreateRejectsOversizedBody(t *testing.T) {
	e := newEnv(t)
	body := `{"url":"https://example.com/` + strings.Repeat("a", maxRequestBodyLen) + `"}`
	wantJSONError(t, e.create(body), http.StatusBadRequest)
}

func TestCreateRequiresJSONContentType(t *testing.T) {
	e := newEnv(t)
	rec := e.do(http.MethodPost, "/api/links", `{"url":"https://example.com"}`,
		map[string]string{"Authorization": "Bearer " + testToken, "Content-Type": "text/plain"})
	wantJSONError(t, rec, http.StatusUnsupportedMediaType)

	rec = e.do(http.MethodPost, "/api/links", `{"url":"https://example.com"}`,
		map[string]string{"Authorization": "Bearer " + testToken, "Content-Type": "application/json; charset=utf-8"})
	wantStatus(t, rec, http.StatusCreated)
}

func TestWriteEndpointsRequireToken(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"guarded"}`), http.StatusCreated)

	bad := map[string]map[string]string{
		"missing":      nil,
		"wrong token":  {"Authorization": "Bearer nope-nope-nope-nope"},
		"prefix token": {"Authorization": "Bearer " + testToken[:len(testToken)-1]},
		"wrong scheme": {"Authorization": "Basic " + testToken},
		"no scheme":    {"Authorization": testToken},
		"empty bearer": {"Authorization": "Bearer "},
	}
	for name, hdr := range bad {
		t.Run(name, func(t *testing.T) {
			rec := e.do(http.MethodPost, "/api/links", `{"url":"https://example.com"}`, hdr)
			wantJSONError(t, rec, http.StatusUnauthorized)
			if rec.Header().Get("WWW-Authenticate") == "" {
				t.Error("missing WWW-Authenticate header")
			}
			wantJSONError(t, e.do(http.MethodDelete, "/api/links/guarded", "", hdr), http.StatusUnauthorized)
		})
	}

	// Auth is checked before input validation, so unauthenticated callers
	// learn nothing about the payload rules.
	wantJSONError(t, e.do(http.MethodPost, "/api/links", `not json`, nil), http.StatusUnauthorized)

	// The link survived all the unauthorised delete attempts.
	wantStatus(t, e.do(http.MethodGet, "/api/links/guarded", "", nil), http.StatusOK)

	// Scheme matching is case-insensitive per RFC 7235.
	rec := e.do(http.MethodPost, "/api/links", `{"url":"https://example.com"}`,
		map[string]string{"Authorization": "bearer " + testToken})
	wantStatus(t, rec, http.StatusCreated)
}

func TestRedirectCountsVisits(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com/target","slug":"go-here"}`), http.StatusCreated)

	for range 3 {
		rec := e.do(http.MethodGet, "/go-here", "", nil)
		wantStatus(t, rec, http.StatusFound)
		if loc := rec.Header().Get("Location"); loc != "https://example.com/target" {
			t.Fatalf("Location = %q", loc)
		}
		if cc := rec.Header().Get("Cache-Control"); !strings.Contains(cc, "no-store") {
			t.Fatalf("Cache-Control = %q, want no-store", cc)
		}
	}
	// HEAD resolves the link without counting a visit.
	wantStatus(t, e.do(http.MethodHead, "/go-here", "", nil), http.StatusFound)

	rec := e.do(http.MethodGet, "/api/links/go-here", "", nil)
	wantStatus(t, rec, http.StatusOK)
	body := decode[map[string]any](t, rec)
	if body["visits"] != float64(3) {
		t.Fatalf("visits = %v, want 3", body["visits"])
	}
	if body["slug"] != "go-here" || body["url"] != "https://example.com/target" ||
		body["short_url"] != "https://sn.ip/go-here" || body["created_at"] != "2026-11-09T12:00:00Z" {
		t.Fatalf("unexpected metadata %v", body)
	}
}

func TestMetadataIncludesZeroVisits(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"fresh"}`), http.StatusCreated)
	body := decode[map[string]any](t, e.do(http.MethodGet, "/api/links/fresh", "", nil))
	if v, ok := body["visits"]; !ok || v != float64(0) {
		t.Fatalf("visits = %v (present=%v), want 0", v, ok)
	}
}

func TestUnknownSlugs(t *testing.T) {
	e := newEnv(t)
	for _, path := range []string{"/nope", "/ab", "/" + strings.Repeat("x", 40), "/bad.slug"} {
		wantJSONError(t, e.do(http.MethodGet, path, "", nil), http.StatusNotFound)
	}
	wantJSONError(t, e.do(http.MethodGet, "/api/links/nope", "", nil), http.StatusNotFound)
	wantJSONError(t, e.do(http.MethodDelete, "/api/links/nope", "", auth), http.StatusNotFound)
}

func TestDelete(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"gone"}`), http.StatusCreated)

	rec := e.do(http.MethodDelete, "/api/links/gone", "", auth)
	wantStatus(t, rec, http.StatusNoContent)
	if rec.Body.Len() != 0 {
		t.Fatalf("expected empty body, got %q", rec.Body.String())
	}

	wantJSONError(t, e.do(http.MethodGet, "/gone", "", nil), http.StatusNotFound)
	wantJSONError(t, e.do(http.MethodGet, "/api/links/gone", "", nil), http.StatusNotFound)
	wantJSONError(t, e.do(http.MethodDelete, "/api/links/gone", "", auth), http.StatusNotFound)

	// The slug can be reused once deleted.
	wantStatus(t, e.create(`{"url":"https://example.org","slug":"gone"}`), http.StatusCreated)
}

func TestPersistsAcrossRestart(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.create(`{"url":"https://example.com","slug":"durable"}`), http.StatusCreated)
	wantStatus(t, e.do(http.MethodGet, "/durable", "", nil), http.StatusFound)
	e.store.Close()

	st, err := store.Open(context.Background(), e.dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	restarted := &testEnv{t: t, srv: New(st, Config{APIToken: testToken, BaseURL: "https://sn.ip"}), store: st}

	rec := restarted.do(http.MethodGet, "/api/links/durable", "", nil)
	wantStatus(t, rec, http.StatusOK)
	if v := decode[map[string]any](t, rec)["visits"]; v != float64(1) {
		t.Fatalf("visits after restart = %v, want 1", v)
	}
	wantStatus(t, restarted.do(http.MethodGet, "/durable", "", nil), http.StatusFound)
}

func TestSecurityHeaders(t *testing.T) {
	e := newEnv(t)
	rec := e.do(http.MethodGet, "/healthz", "", nil)
	if rec.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Error("missing nosniff")
	}
	if !strings.Contains(rec.Header().Get("Content-Security-Policy"), "default-src 'none'") {
		t.Error("missing CSP")
	}
}

func TestMethodNotAllowed(t *testing.T) {
	e := newEnv(t)
	wantStatus(t, e.do(http.MethodPut, "/api/links/abc", "", auth), http.StatusMethodNotAllowed)
	wantStatus(t, e.do(http.MethodGet, "/api/links", "", nil), http.StatusMethodNotAllowed)
}

func TestPanicRecovery(t *testing.T) {
	s := &Server{log: newEnv(t).srv.log}
	h := s.recoverPanics(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") }))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	wantJSONError(t, rec, http.StatusInternalServerError)
}
