package store_test

import (
	"errors"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/example/snip/internal/store"
)

func TestPersistsAcrossRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "snip.db")
	s, err := store.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Create("abc", "https://example.com", time.Now()); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Visit("abc"); err != nil {
		t.Fatal(err)
	}
	s.Close()

	s, err = store.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	l, err := s.Get("abc")
	if err != nil {
		t.Fatal(err)
	}
	if l.URL != "https://example.com" || l.Visits != 1 {
		t.Errorf("got %+v", l)
	}
	if _, err := s.Create("abc", "x", time.Now()); !errors.Is(err, store.ErrExists) {
		t.Errorf("want ErrExists, got %v", err)
	}
}

func TestConcurrentVisits(t *testing.T) {
	s, err := store.Open(filepath.Join(t.TempDir(), "snip.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Create("abc", "https://example.com", time.Now())
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); s.Visit("abc") }()
	}
	wg.Wait()
	if l, _ := s.Get("abc"); l.Visits != 50 {
		t.Errorf("visits %d", l.Visits)
	}
}
