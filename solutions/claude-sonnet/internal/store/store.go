// Package store persists links in a local SQLite database.
package store

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

var (
	// ErrExists is returned when a slug is already taken.
	ErrExists = errors.New("slug already exists")
	// ErrNotFound is returned when a slug does not exist.
	ErrNotFound = errors.New("link not found")
)

// Link is a shortened URL.
type Link struct {
	Slug      string
	URL       string
	CreatedAt time.Time
	Visits    int64
}

// Store is a SQLite-backed link store.
type Store struct {
	db *sql.DB
}

const schema = `
CREATE TABLE IF NOT EXISTS links (
	slug       TEXT PRIMARY KEY,
	url        TEXT NOT NULL,
	created_at TEXT NOT NULL,
	visits     INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;`

// Open opens (creating if needed) the database at path. Use ":memory:" for tests.
func Open(path string) (*Store, error) {
	dsn := path
	if path != ":memory:" {
		dsn = fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)", path)
	}
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	// A single connection serialises writes and keeps ":memory:" coherent.
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(schema); err != nil {
		db.Close()
		return nil, fmt.Errorf("init schema: %w", err)
	}
	return &Store{db: db}, nil
}

// Close releases the database.
func (s *Store) Close() error { return s.db.Close() }

// Ping checks the database is reachable.
func (s *Store) Ping() error { return s.db.Ping() }

// Create inserts a new link, returning ErrExists if the slug is taken.
func (s *Store) Create(slug, url string, now time.Time) (Link, error) {
	l := Link{Slug: slug, URL: url, CreatedAt: now.UTC().Truncate(time.Second)}
	// INSERT OR IGNORE avoids depending on driver-specific error codes.
	res, err := s.db.Exec(
		`INSERT OR IGNORE INTO links (slug, url, created_at) VALUES (?, ?, ?)`,
		l.Slug, l.URL, l.CreatedAt.Format(time.RFC3339),
	)
	if err != nil {
		return Link{}, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return Link{}, err
	}
	if n == 0 {
		return Link{}, ErrExists
	}
	return l, nil
}

// Get returns the link for slug.
func (s *Store) Get(slug string) (Link, error) {
	var (
		l       Link
		created string
	)
	err := s.db.QueryRow(
		`SELECT slug, url, created_at, visits FROM links WHERE slug = ?`, slug,
	).Scan(&l.Slug, &l.URL, &created, &l.Visits)
	if errors.Is(err, sql.ErrNoRows) {
		return Link{}, ErrNotFound
	}
	if err != nil {
		return Link{}, err
	}
	l.CreatedAt, err = time.Parse(time.RFC3339, created)
	return l, err
}

// Visit atomically increments the visit counter and returns the target URL.
func (s *Store) Visit(slug string) (string, error) {
	var url string
	err := s.db.QueryRow(
		`UPDATE links SET visits = visits + 1 WHERE slug = ? RETURNING url`, slug,
	).Scan(&url)
	if errors.Is(err, sql.ErrNoRows) {
		return "", ErrNotFound
	}
	return url, err
}

// Delete removes a link.
func (s *Store) Delete(slug string) error {
	res, err := s.db.Exec(`DELETE FROM links WHERE slug = ?`, slug)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if n == 0 {
		return ErrNotFound
	}
	return nil
}
