// Package server implements the snip HTTP API.
package server

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"log/slog"
	"math/big"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"

	"github.com/example/snip/internal/store"
)

const (
	maxURLLen      = 2048
	minSlugLen     = 3
	maxSlugLen     = 32
	generatedLen   = 8
	maxBodyBytes   = 16 << 10
	maxGenAttempts = 10
	alphabet       = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)

var (
	slugRe = regexp.MustCompile(`^[A-Za-z0-9_-]{3,32}$`)
	// Slugs that would shadow application routes.
	reserved = map[string]bool{"api": true, "healthz": true}
)

// Config configures a Server.
type Config struct {
	Store   *store.Store
	Token   string // bearer token for write endpoints (required)
	BaseURL string // public base URL used in short_url; derived from the request if empty
	Logger  *slog.Logger
	Now     func() time.Time
}

// Server is the HTTP handler.
type Server struct {
	cfg Config
	mux *http.ServeMux
}

// New builds a Server. It panics if no token is configured, so a
// misconfigured deployment can never expose unauthenticated writes.
func New(cfg Config) *Server {
	if cfg.Token == "" {
		panic("server: empty API token")
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	cfg.BaseURL = strings.TrimRight(cfg.BaseURL, "/")
	s := &Server{cfg: cfg, mux: http.NewServeMux()}
	s.mux.HandleFunc("GET /healthz", s.health)
	s.mux.HandleFunc("POST /api/links", s.auth(s.create))
	s.mux.HandleFunc("GET /api/links/{slug}", s.get)
	s.mux.HandleFunc("DELETE /api/links/{slug}", s.auth(s.delete))
	s.mux.HandleFunc("GET /{slug}", s.redirect)
	return s
}

// ServeHTTP implements http.Handler.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
	s.mux.ServeHTTP(rec, r)
	s.cfg.Logger.Info("request", "method", r.Method, "path", r.URL.Path, "status", rec.status)
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

type linkResponse struct {
	Slug      string `json:"slug"`
	URL       string `json:"url"`
	ShortURL  string `json:"short_url"`
	CreatedAt string `json:"created_at"`
	Visits    *int64 `json:"visits,omitempty"`
}

func (s *Server) toResponse(r *http.Request, l store.Link, withVisits bool) linkResponse {
	resp := linkResponse{
		Slug:      l.Slug,
		URL:       l.URL,
		ShortURL:  s.baseURL(r) + "/" + l.Slug,
		CreatedAt: l.CreatedAt.UTC().Format(time.RFC3339),
	}
	if withVisits {
		v := l.Visits
		resp.Visits = &v
	}
	return resp
}

func (s *Server) baseURL(r *http.Request) string {
	if s.cfg.BaseURL != "" {
		return s.cfg.BaseURL
	}
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	return scheme + "://" + r.Host
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func (s *Server) internalError(w http.ResponseWriter, err error) {
	s.cfg.Logger.Error("internal error", "err", err)
	writeError(w, http.StatusInternalServerError, "internal server error")
}

// auth guards a handler with the bearer token.
func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		scheme, tok, ok := strings.Cut(h, " ")
		valid := ok && strings.EqualFold(scheme, "Bearer") &&
			subtle.ConstantTimeCompare([]byte(strings.TrimSpace(tok)), []byte(s.cfg.Token)) == 1
		if !valid {
			w.Header().Set("WWW-Authenticate", `Bearer realm="snip"`)
			writeError(w, http.StatusUnauthorized, "missing or invalid bearer token")
			return
		}
		next(w, r)
	}
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if err := s.cfg.Store.Ping(); err != nil {
		writeError(w, http.StatusServiceUnavailable, "storage unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

type createRequest struct {
	URL  *string `json:"url"`
	Slug *string `json:"slug"`
}

func (s *Server) create(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req createRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			writeError(w, http.StatusRequestEntityTooLarge, "request body too large")
			return
		}
		writeError(w, http.StatusBadRequest, "body must be a JSON object")
		return
	}
	if req.URL == nil {
		writeError(w, http.StatusBadRequest, "url is required")
		return
	}
	if err := validateURL(*req.URL); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	now := s.cfg.Now()
	if req.Slug != nil && *req.Slug != "" {
		slug := *req.Slug
		if !slugRe.MatchString(slug) {
			writeError(w, http.StatusBadRequest, "slug must be 3-32 characters of A-Z, a-z, 0-9, '_' or '-'")
			return
		}
		if reserved[strings.ToLower(slug)] {
			writeError(w, http.StatusBadRequest, "slug is reserved")
			return
		}
		l, err := s.cfg.Store.Create(slug, *req.URL, now)
		switch {
		case errors.Is(err, store.ErrExists):
			writeError(w, http.StatusConflict, "slug already taken")
		case err != nil:
			s.internalError(w, err)
		default:
			writeJSON(w, http.StatusCreated, s.toResponse(r, l, false))
		}
		return
	}

	for i := 0; i < maxGenAttempts; i++ {
		slug, err := randomSlug(generatedLen)
		if err != nil {
			s.internalError(w, err)
			return
		}
		if reserved[strings.ToLower(slug)] {
			continue
		}
		l, err := s.cfg.Store.Create(slug, *req.URL, now)
		if errors.Is(err, store.ErrExists) {
			continue
		}
		if err != nil {
			s.internalError(w, err)
			return
		}
		writeJSON(w, http.StatusCreated, s.toResponse(r, l, false))
		return
	}
	s.internalError(w, errors.New("could not generate a unique slug"))
}

func (s *Server) get(w http.ResponseWriter, r *http.Request) {
	l, err := s.cfg.Store.Get(r.PathValue("slug"))
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, "link not found")
	case err != nil:
		s.internalError(w, err)
	default:
		writeJSON(w, http.StatusOK, s.toResponse(r, l, true))
	}
}

func (s *Server) delete(w http.ResponseWriter, r *http.Request) {
	err := s.cfg.Store.Delete(r.PathValue("slug"))
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, "link not found")
	case err != nil:
		s.internalError(w, err)
	default:
		w.WriteHeader(http.StatusNoContent)
	}
}

func (s *Server) redirect(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	var (
		target string
		err    error
	)
	if r.Method == http.MethodHead {
		var l store.Link
		l, err = s.cfg.Store.Get(slug)
		target = l.URL
	} else {
		target, err = s.cfg.Store.Visit(slug)
	}
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, "link not found")
	case err != nil:
		s.internalError(w, err)
	default:
		w.Header().Set("Location", target)
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusFound)
	}
}

func validateURL(raw string) error {
	if raw == "" {
		return errors.New("url is required")
	}
	if len(raw) > maxURLLen {
		return errors.New("url must be at most 2048 characters")
	}
	for _, c := range raw {
		if unicode.IsSpace(c) || unicode.IsControl(c) {
			return errors.New("url must not contain whitespace or control characters")
		}
	}
	u, err := url.Parse(raw)
	if err != nil || !u.IsAbs() {
		return errors.New("url must be an absolute http or https URL")
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return errors.New("url scheme must be http or https")
	}
	if u.Hostname() == "" {
		return errors.New("url must include a host")
	}
	return nil
}

func randomSlug(n int) (string, error) {
	b := make([]byte, n)
	max := big.NewInt(int64(len(alphabet)))
	for i := range b {
		v, err := rand.Int(rand.Reader, max)
		if err != nil {
			return "", err
		}
		b[i] = alphabet[v.Int64()]
	}
	return string(b), nil
}
