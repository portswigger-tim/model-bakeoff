// Package server implements the snip HTTP API.
package server

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"strings"
	"time"

	"snip/internal/store"
)

// maxSlugAttempts bounds retries when a generated slug collides.
const maxSlugAttempts = 5

// Config configures a Server.
type Config struct {
	// APIToken is the bearer token required by write endpoints.
	APIToken string
	// BaseURL prefixes slugs to build short_url, e.g. "https://sn.ip".
	BaseURL string
	Logger  *slog.Logger
	// Now and NewSlug may be overridden in tests.
	Now     func() time.Time
	NewSlug func() (string, error)
}

// Server serves the snip API.
type Server struct {
	store     *store.Store
	tokenHash [sha256.Size]byte
	baseURL   string
	log       *slog.Logger
	now       func() time.Time
	newSlug   func() (string, error)
	handler   http.Handler
}

// New returns a Server backed by st.
func New(st *store.Store, cfg Config) *Server {
	s := &Server{
		store:     st,
		tokenHash: sha256.Sum256([]byte(cfg.APIToken)),
		baseURL:   strings.TrimRight(cfg.BaseURL, "/"),
		log:       cfg.Logger,
		now:       cfg.Now,
		newSlug:   cfg.NewSlug,
	}
	if s.log == nil {
		s.log = slog.New(slog.DiscardHandler)
	}
	if s.now == nil {
		s.now = time.Now
	}
	if s.newSlug == nil {
		s.newSlug = randomSlug
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.handleHealth)
	mux.Handle("POST /api/links", s.requireToken(http.HandlerFunc(s.handleCreate)))
	mux.HandleFunc("GET /api/links/{slug}", s.handleGet)
	mux.Handle("DELETE /api/links/{slug}", s.requireToken(http.HandlerFunc(s.handleDelete)))
	mux.HandleFunc("GET /{slug}", s.handleRedirect)

	s.handler = s.recoverPanics(s.logRequests(securityHeaders(mux)))
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.handler.ServeHTTP(w, r)
}

type createRequest struct {
	URL  string `json:"url"`
	Slug string `json:"slug"`
}

type linkResponse struct {
	Slug      string `json:"slug"`
	URL       string `json:"url"`
	ShortURL  string `json:"short_url"`
	CreatedAt string `json:"created_at"`
	Visits    *int64 `json:"visits,omitempty"`
}

func (s *Server) toResponse(l store.Link, withVisits bool) linkResponse {
	resp := linkResponse{
		Slug:      l.Slug,
		URL:       l.URL,
		ShortURL:  s.baseURL + "/" + l.Slug,
		CreatedAt: l.CreatedAt.UTC().Format(time.RFC3339),
	}
	if withVisits {
		v := l.Visits
		resp.Visits = &v
	}
	return resp
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.store.Ping(ctx); err != nil {
		s.log.Error("health check failed", "err", err)
		writeError(w, http.StatusServiceUnavailable, "storage unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) handleCreate(w http.ResponseWriter, r *http.Request) {
	if mt, _, err := mime.ParseMediaType(r.Header.Get("Content-Type")); err != nil || mt != "application/json" {
		writeError(w, http.StatusUnsupportedMediaType, "Content-Type must be application/json")
		return
	}

	var req createRequest
	if err := decodeJSON(w, r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := validateURL(req.URL); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	link := store.Link{URL: req.URL, CreatedAt: s.now().UTC().Truncate(time.Second)}

	if req.Slug != "" {
		if err := validateSlug(req.Slug); err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		link.Slug = req.Slug
		if err := s.store.Create(r.Context(), link); err != nil {
			if errors.Is(err, store.ErrSlugTaken) {
				writeError(w, http.StatusConflict, "slug already taken")
				return
			}
			s.internalError(w, "create link", err)
			return
		}
	} else if err := s.createWithGeneratedSlug(r.Context(), &link); err != nil {
		s.internalError(w, "create link", err)
		return
	}

	w.Header().Set("Location", "/api/links/"+link.Slug)
	writeJSON(w, http.StatusCreated, s.toResponse(link, false))
}

// createWithGeneratedSlug inserts link under a fresh random slug, retrying on
// the (astronomically unlikely) event of a collision. Uniqueness is enforced
// by the database primary key, so concurrent creators cannot both win.
func (s *Server) createWithGeneratedSlug(ctx context.Context, link *store.Link) error {
	for range maxSlugAttempts {
		slug, err := s.newSlug()
		if err != nil {
			return err
		}
		if validateSlug(slug) != nil {
			continue
		}
		link.Slug = slug
		err = s.store.Create(ctx, *link)
		if err == nil {
			return nil
		}
		if !errors.Is(err, store.ErrSlugTaken) {
			return err
		}
	}
	return errors.New("could not generate a unique slug")
}

func (s *Server) handleGet(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if !slugPattern.MatchString(slug) {
		writeError(w, http.StatusNotFound, "link not found")
		return
	}
	link, err := s.store.Get(r.Context(), slug)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "link not found")
			return
		}
		s.internalError(w, "get link", err)
		return
	}
	writeJSON(w, http.StatusOK, s.toResponse(link, true))
}

func (s *Server) handleDelete(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if !slugPattern.MatchString(slug) {
		writeError(w, http.StatusNotFound, "link not found")
		return
	}
	if err := s.store.Delete(r.Context(), slug); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "link not found")
			return
		}
		s.internalError(w, "delete link", err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleRedirect(w http.ResponseWriter, r *http.Request) {
	slug := r.PathValue("slug")
	if !slugPattern.MatchString(slug) {
		writeError(w, http.StatusNotFound, "link not found")
		return
	}

	var (
		link store.Link
		err  error
	)
	// HEAD requests (link previews, uptime checkers) don't count as visits.
	if r.Method == http.MethodHead {
		link, err = s.store.Get(r.Context(), slug)
	} else {
		link, err = s.store.Visit(r.Context(), slug)
	}
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "link not found")
			return
		}
		s.internalError(w, "resolve link", err)
		return
	}

	// Don't let browsers or proxies cache the redirect, or visits go uncounted.
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("Location", link.URL)
	w.WriteHeader(http.StatusFound)
}

// requireToken rejects requests lacking the configured bearer token.
func (s *Server) requireToken(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		scheme, token, ok := strings.Cut(r.Header.Get("Authorization"), " ")
		// Compare fixed-length digests so the check is constant-time and
		// doesn't leak the token length.
		given := sha256.Sum256([]byte(strings.TrimSpace(token)))
		if !ok || !strings.EqualFold(scheme, "Bearer") ||
			subtle.ConstantTimeCompare(given[:], s.tokenHash[:]) != 1 {
			w.Header().Set("WWW-Authenticate", `Bearer realm="snip"`)
			writeError(w, http.StatusUnauthorized, "missing or invalid bearer token")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) internalError(w http.ResponseWriter, op string, err error) {
	s.log.Error(op, "err", err)
	writeError(w, http.StatusInternalServerError, "internal server error")
}

// decodeJSON decodes exactly one JSON object from a size-limited body.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyLen)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		var maxErr *http.MaxBytesError
		var typeErr *json.UnmarshalTypeError
		switch {
		case errors.As(err, &maxErr):
			return errors.New("request body too large")
		case errors.As(err, &typeErr) && typeErr.Field != "":
			return errors.New("field " + typeErr.Field + " must be a string")
		case errors.Is(err, io.EOF):
			return errors.New("request body must not be empty")
		case strings.HasPrefix(err.Error(), "json: unknown field"):
			return errors.New(strings.TrimPrefix(err.Error(), "json: "))
		default:
			return errors.New("request body must be a JSON object")
		}
	}
	if dec.More() {
		return errors.New("request body must contain a single JSON object")
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
