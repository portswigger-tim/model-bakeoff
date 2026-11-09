package store

import (
	"context"
	"errors"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func openTemp(t *testing.T) (*Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "nested", "snip.db")
	s, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s, path
}

func TestCreateGetDelete(t *testing.T) {
	ctx := context.Background()
	s, _ := openTemp(t)
	now := time.Date(2026, 1, 2, 3, 4, 5, 6, time.UTC)

	if err := s.Create(ctx, Link{Slug: "abc", URL: "https://example.com", CreatedAt: now}); err != nil {
		t.Fatalf("Create: %v", err)
	}
	got, err := s.Get(ctx, "abc")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.URL != "https://example.com" || got.Visits != 0 || !got.CreatedAt.Equal(now) {
		t.Fatalf("unexpected link: %+v", got)
	}

	if err := s.Create(ctx, Link{Slug: "abc", URL: "https://other.example", CreatedAt: now}); !errors.Is(err, ErrSlugTaken) {
		t.Fatalf("duplicate Create: got %v, want ErrSlugTaken", err)
	}

	if err := s.Delete(ctx, "abc"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := s.Get(ctx, "abc"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get after delete: got %v, want ErrNotFound", err)
	}
	if err := s.Delete(ctx, "abc"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("second Delete: got %v, want ErrNotFound", err)
	}
}

func TestSlugsAreCaseSensitive(t *testing.T) {
	ctx := context.Background()
	s, _ := openTemp(t)
	if err := s.Create(ctx, Link{Slug: "Abc", URL: "https://a.example", CreatedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if err := s.Create(ctx, Link{Slug: "abc", URL: "https://b.example", CreatedAt: time.Now()}); err != nil {
		t.Fatalf("distinct-case slug should be allowed: %v", err)
	}
}

func TestVisitIncrementsAtomically(t *testing.T) {
	ctx := context.Background()
	s, _ := openTemp(t)
	if err := s.Create(ctx, Link{Slug: "hits", URL: "https://example.com", CreatedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}

	const n = 50
	var wg sync.WaitGroup
	for range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.Visit(ctx, "hits"); err != nil {
				t.Errorf("Visit: %v", err)
			}
		}()
	}
	wg.Wait()

	got, err := s.Get(ctx, "hits")
	if err != nil {
		t.Fatal(err)
	}
	if got.Visits != n {
		t.Fatalf("visits = %d, want %d", got.Visits, n)
	}
	if _, err := s.Visit(ctx, "missing"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Visit missing: got %v, want ErrNotFound", err)
	}
}

func TestPersistsAcrossReopen(t *testing.T) {
	ctx := context.Background()
	s, path := openTemp(t)
	if err := s.Create(ctx, Link{Slug: "keep", URL: "https://example.com", CreatedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Visit(ctx, "keep"); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}

	s2, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer s2.Close()
	got, err := s2.Get(ctx, "keep")
	if err != nil {
		t.Fatalf("Get after reopen: %v", err)
	}
	if got.Visits != 1 {
		t.Fatalf("visits after reopen = %d, want 1", got.Visits)
	}
}
