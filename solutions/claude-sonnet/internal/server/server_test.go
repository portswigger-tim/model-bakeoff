package server_test

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/example/snip/internal/server"
	"github.com/example/snip/internal/store"
)

const token = "s3cret"

func newServer(t *testing.T) (http.Handler, *store.Store) {
	t.Helper()
	st, err := store.Open(filepath.Join(t.TempDir(), "t.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return server.New(server.Config{
		Store:   st,
		Token:   token,
		BaseURL: "https://snip.test/",
		Now:     func() time.Time { return time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC) },
	}), st
}

func do(h http.Handler, method, path, body, auth string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &m); err != nil {
		t.Fatalf("body not JSON: %q", rec.Body.String())
	}
	return m
}

func create(t *testing.T, h http.Handler, body string) map[string]any {
	t.Helper()
	rec := do(h, "POST", "/api/links", body, "Bearer "+token)
	if rec.Code != 201 {
		t.Fatalf("create %s: %d %s", body, rec.Code, rec.Body)
	}
	return decode(t, rec)
}

func TestHealthz(t *testing.T) {
	h, _ := newServer(t)
	if rec := do(h, "GET", "/healthz", "", ""); rec.Code != 200 {
		t.Fatalf("got %d", rec.Code)
	}
}

func TestCreateGeneratedSlug(t *testing.T) {
	h, _ := newServer(t)
	m := create(t, h, `{"url":"https://example.com/a?b=c"}`)
	slug := m["slug"].(string)
	if len(slug) != 8 {
		t.Errorf("slug %q", slug)
	}
	if m["url"] != "https://example.com/a?b=c" ||
		m["short_url"] != "https://snip.test/"+slug ||
		m["created_at"] != "2026-01-02T03:04:05Z" {
		t.Errorf("unexpected body %v", m)
	}
}

func TestGeneratedSlugsUnique(t *testing.T) {
	h, _ := newServer(t)
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		s := create(t, h, `{"url":"http://example.com"}`)["slug"].(string)
		if seen[s] {
			t.Fatalf("duplicate slug %s", s)
		}
		seen[s] = true
	}
}

func TestCustomSlugAndConflict(t *testing.T) {
	h, _ := newServer(t)
	m := create(t, h, `{"url":"https://example.com","slug":"my-Link_1"}`)
	if m["slug"] != "my-Link_1" {
		t.Errorf("slug %v", m["slug"])
	}
	rec := do(h, "POST", "/api/links", `{"url":"https://other.com","slug":"my-Link_1"}`, "Bearer "+token)
	if rec.Code != 409 {
		t.Fatalf("got %d", rec.Code)
	}
	if decode(t, rec)["error"] == nil {
		t.Error("no error body")
	}
}

func TestCreateValidation(t *testing.T) {
	h, _ := newServer(t)
	long := "https://example.com/" + strings.Repeat("a", 2048)
	exact := "https://example.com/" + strings.Repeat("a", 2048-len("https://example.com/"))
	bad := map[string]string{
		"not json":       `nope`,
		"empty object":   `{}`,
		"missing url":    `{"slug":"abc"}`,
		"url not string": `{"url":5}`,
		"relative":       `{"url":"/foo"}`,
		"no scheme":      `{"url":"example.com"}`,
		"ftp":            `{"url":"ftp://example.com/x"}`,
		"javascript":     `{"url":"javascript:alert(1)"}`,
		"no host":        `{"url":"http://"}`,
		"whitespace":     `{"url":"http://exa mple.com"}`,
		"too long":       `{"url":"` + long + `"}`,
		"slug short":     `{"url":"http://a.com","slug":"ab"}`,
		"slug long":      `{"url":"http://a.com","slug":"` + strings.Repeat("a", 33) + `"}`,
		"slug chars":     `{"url":"http://a.com","slug":"a/b c"}`,
		"slug reserved":  `{"url":"http://a.com","slug":"api"}`,
		"slug not str":   `{"url":"http://a.com","slug":7}`,
	}
	for name, body := range bad {
		rec := do(h, "POST", "/api/links", body, "Bearer "+token)
		if rec.Code != 400 {
			t.Errorf("%s: got %d", name, rec.Code)
			continue
		}
		if decode(t, rec)["error"] == nil {
			t.Errorf("%s: no error body", name)
		}
	}
	if len(exact) != 2048 {
		t.Fatal("test bug")
	}
	create(t, h, `{"url":"`+exact+`"}`)
}

func TestBodyTooLarge(t *testing.T) {
	h, _ := newServer(t)
	rec := do(h, "POST", "/api/links", `{"url":"http://a.com","x":"`+strings.Repeat("a", 20000)+`"}`, "Bearer "+token)
	if rec.Code != 413 {
		t.Fatalf("got %d", rec.Code)
	}
}

func TestAuth(t *testing.T) {
	h, _ := newServer(t)
	create(t, h, `{"url":"http://a.com","slug":"abc"}`)
	for _, auth := range []string{"", "Bearer wrong", "Bearer ", "Basic " + token, token} {
		if rec := do(h, "POST", "/api/links", `{"url":"http://a.com"}`, auth); rec.Code != 401 {
			t.Errorf("POST auth %q: got %d", auth, rec.Code)
		}
		if rec := do(h, "DELETE", "/api/links/abc", "", auth); rec.Code != 401 {
			t.Errorf("DELETE auth %q: got %d", auth, rec.Code)
		}
	}
	// still there; reads need no auth
	if rec := do(h, "GET", "/api/links/abc", "", ""); rec.Code != 200 {
		t.Errorf("get: %d", rec.Code)
	}
}

func TestRedirectCountsVisits(t *testing.T) {
	h, _ := newServer(t)
	create(t, h, `{"url":"https://example.com/x","slug":"go-go"}`)
	for i := 0; i < 3; i++ {
		rec := do(h, "GET", "/go-go", "", "")
		if rec.Code != 302 || rec.Header().Get("Location") != "https://example.com/x" {
			t.Fatalf("got %d %q", rec.Code, rec.Header().Get("Location"))
		}
	}
	do(h, "HEAD", "/go-go", "", "") // HEAD does not count
	m := decode(t, do(h, "GET", "/api/links/go-go", "", ""))
	if m["visits"] != float64(3) {
		t.Errorf("visits %v", m["visits"])
	}
	if m["url"] != "https://example.com/x" || m["short_url"] != "https://snip.test/go-go" || m["created_at"] == nil {
		t.Errorf("metadata %v", m)
	}
}

func TestNotFound(t *testing.T) {
	h, _ := newServer(t)
	if rec := do(h, "GET", "/nothere", "", ""); rec.Code != 404 {
		t.Errorf("redirect: %d", rec.Code)
	}
	if rec := do(h, "GET", "/api/links/nothere", "", ""); rec.Code != 404 {
		t.Errorf("get: %d", rec.Code)
	}
	if rec := do(h, "DELETE", "/api/links/nothere", "", "Bearer "+token); rec.Code != 404 {
		t.Errorf("delete: %d", rec.Code)
	}
}

func TestDelete(t *testing.T) {
	h, _ := newServer(t)
	create(t, h, `{"url":"https://example.com","slug":"bye"}`)
	if rec := do(h, "DELETE", "/api/links/bye", "", "Bearer "+token); rec.Code != 204 {
		t.Fatalf("got %d", rec.Code)
	}
	if rec := do(h, "GET", "/bye", "", ""); rec.Code != 404 {
		t.Errorf("after delete: %d", rec.Code)
	}
	// slug becomes reusable
	create(t, h, `{"url":"https://example.com","slug":"bye"}`)
}

func TestDerivedBaseURL(t *testing.T) {
	st, _ := store.Open(":memory:")
	defer st.Close()
	h := server.New(server.Config{Store: st, Token: token})
	req := httptest.NewRequest("POST", "http://short.example:9000/api/links", strings.NewReader(`{"url":"http://a.com","slug":"abc"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	b, _ := io.ReadAll(rec.Body)
	if !strings.Contains(string(b), `"short_url":"http://short.example:9000/abc"`) {
		t.Errorf("got %s", b)
	}
}

func TestEmptyTokenPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Error("expected panic")
		}
	}()
	server.New(server.Config{})
}
