// Command snip runs the URL-shortener HTTP service.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/example/snip/internal/server"
	"github.com/example/snip/internal/store"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))

	token := os.Getenv("SNIP_API_TOKEN")
	if token == "" {
		log.Error("SNIP_API_TOKEN must be set")
		os.Exit(1)
	}
	dbPath := env("SNIP_DB_PATH", "data/snip.db")
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o750); err != nil {
		log.Error("create data dir", "err", err)
		os.Exit(1)
	}
	st, err := store.Open(dbPath)
	if err != nil {
		log.Error("open store", "err", err)
		os.Exit(1)
	}
	defer st.Close()

	srv := &http.Server{
		Addr: env("SNIP_ADDR", "127.0.0.1:8080"),
		Handler: server.New(server.Config{
			Store:   st,
			Token:   token,
			BaseURL: os.Getenv("SNIP_BASE_URL"),
			Logger:  log,
		}),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdown)
	}()

	log.Info("listening", "addr", srv.Addr, "db", dbPath)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Error("server", "err", err)
		os.Exit(1)
	}
}
