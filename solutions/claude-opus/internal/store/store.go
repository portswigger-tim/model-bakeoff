// Package store persists short links in a local SQLite database.
package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"modernc.org/sqlite"
	sqlite3 "modernc.org/sqlite/lib"
)

var (
	// ErrNotFound is returned when no link exists for a slug.
	ErrNotFound = errors.New("link not found")
	// ErrSlugTaken is returned when inserting a slug that already exists.
	ErrSlugTaken = errors.New("slug already taken")
)

// Link is a stored short link.
type Link struct {
	Slug      string
	URL       string
	Visits    int64
	CreatedAt time.Time
}

// Store is a SQLite-backed link store. It is safe for concurrent use.
type Store struct {
	db *sql.DB
}

const schema = `
CREATE TABLE IF NOT EXISTS links (
	slug       TEXT PRIMARY KEY,
	url        TEXT NOT NULL,
	visits     INTEGER NOT NULL DEFAULT 0,
	created_at TEXT NOT NULL
) WITHOUT ROWID;
`

// Open opens (creating if necessary) the database at path and applies the schema.
func Open(ctx context.Context, path string) (*Store, error) {
	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o750); err != nil {
			return nil, fmt.Errorf("create data directory: %w", err)
		}
	}

	dsn := "file:" + path +
		"?_pragma=journal_mode(WAL)" +
		"&_pragma=busy_timeout(5000)" +
		"&_pragma=synchronous(NORMAL)" +
		"&_pragma=foreign_keys(ON)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}
	// A single connection serialises writes and avoids SQLITE_BUSY churn;
	// it is plenty for a service of this size.
	db.SetMaxOpenConns(1)

	if _, err := db.ExecContext(ctx, schema); err != nil {
		db.Close()
		return nil, fmt.Errorf("apply schema: %w", err)
	}
	return &Store{db: db}, nil
}

// Close closes the underlying database.
func (s *Store) Close() error { return s.db.Close() }

// Ping checks the database is reachable.
func (s *Store) Ping(ctx context.Context) error { return s.db.PingContext(ctx) }

// Create inserts a new link. It returns ErrSlugTaken if the slug exists.
func (s *Store) Create(ctx context.Context, l Link) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO links (slug, url, visits, created_at) VALUES (?, ?, 0, ?)`,
		l.Slug, l.URL, l.CreatedAt.UTC().Format(time.RFC3339Nano))
	if err != nil {
		var se *sqlite.Error
		if errors.As(err, &se) && (se.Code() == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY ||
			se.Code() == sqlite3.SQLITE_CONSTRAINT_UNIQUE) {
			return ErrSlugTaken
		}
		return fmt.Errorf("insert link: %w", err)
	}
	return nil
}

// Get returns the link for slug.
func (s *Store) Get(ctx context.Context, slug string) (Link, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT slug, url, visits, created_at FROM links WHERE slug = ?`, slug)
	return scanLink(row)
}

// Visit atomically increments the visit counter for slug and returns the link.
func (s *Store) Visit(ctx context.Context, slug string) (Link, error) {
	row := s.db.QueryRowContext(ctx,
		`UPDATE links SET visits = visits + 1 WHERE slug = ?
		 RETURNING slug, url, visits, created_at`, slug)
	return scanLink(row)
}

// Delete removes the link for slug. It returns ErrNotFound if none existed.
func (s *Store) Delete(ctx context.Context, slug string) error {
	res, err := s.db.ExecContext(ctx, `DELETE FROM links WHERE slug = ?`, slug)
	if err != nil {
		return fmt.Errorf("delete link: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("delete link: %w", err)
	}
	if n == 0 {
		return ErrNotFound
	}
	return nil
}

func scanLink(row *sql.Row) (Link, error) {
	var (
		l       Link
		created string
	)
	if err := row.Scan(&l.Slug, &l.URL, &l.Visits, &created); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return Link{}, ErrNotFound
		}
		return Link{}, fmt.Errorf("scan link: %w", err)
	}
	t, err := time.Parse(time.RFC3339Nano, created)
	if err != nil {
		return Link{}, fmt.Errorf("parse created_at: %w", err)
	}
	l.CreatedAt = t
	return l, nil
}
