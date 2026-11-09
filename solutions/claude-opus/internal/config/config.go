// Package config loads snip's runtime configuration from the environment.
package config

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"strings"
)

// MinTokenLength is the shortest SNIP_API_TOKEN accepted at startup.
const MinTokenLength = 16

// Config is the service configuration.
type Config struct {
	Addr     string // SNIP_ADDR
	DBPath   string // SNIP_DB_PATH
	BaseURL  string // SNIP_BASE_URL
	APIToken string // SNIP_API_TOKEN
}

// Load reads configuration using getenv (typically os.Getenv).
func Load(getenv func(string) string) (Config, error) {
	cfg := Config{
		Addr:     getenv("SNIP_ADDR"),
		DBPath:   getenv("SNIP_DB_PATH"),
		BaseURL:  getenv("SNIP_BASE_URL"),
		APIToken: getenv("SNIP_API_TOKEN"),
	}
	if cfg.Addr == "" {
		cfg.Addr = "127.0.0.1:8080"
	}
	if cfg.DBPath == "" {
		cfg.DBPath = "data/snip.db"
	}

	if cfg.APIToken == "" {
		return Config{}, errors.New("SNIP_API_TOKEN must be set")
	}
	if len(cfg.APIToken) < MinTokenLength {
		return Config{}, fmt.Errorf("SNIP_API_TOKEN must be at least %d characters", MinTokenLength)
	}
	if strings.ContainsAny(cfg.APIToken, " \t\r\n") {
		return Config{}, errors.New("SNIP_API_TOKEN must not contain whitespace")
	}

	_, port, err := net.SplitHostPort(cfg.Addr)
	if err != nil {
		return Config{}, fmt.Errorf("SNIP_ADDR %q is not host:port: %w", cfg.Addr, err)
	}

	if cfg.BaseURL == "" {
		cfg.BaseURL = "http://localhost:" + port
	}
	u, err := url.Parse(cfg.BaseURL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" ||
		u.RawQuery != "" || u.Fragment != "" || u.User != nil {
		return Config{}, fmt.Errorf("SNIP_BASE_URL %q must be an absolute http(s) URL without query or fragment", cfg.BaseURL)
	}
	cfg.BaseURL = strings.TrimRight(cfg.BaseURL, "/")

	return cfg, nil
}
