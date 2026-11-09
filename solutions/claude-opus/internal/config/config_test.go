package config

import (
	"strings"
	"testing"
)

func env(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

const token = "0123456789abcdef0123"

func TestDefaults(t *testing.T) {
	cfg, err := Load(env(map[string]string{"SNIP_API_TOKEN": token}))
	if err != nil {
		t.Fatal(err)
	}
	want := Config{Addr: "127.0.0.1:8080", DBPath: "data/snip.db", BaseURL: "http://localhost:8080", APIToken: token}
	if cfg != want {
		t.Fatalf("got %+v, want %+v", cfg, want)
	}
}

func TestOverrides(t *testing.T) {
	cfg, err := Load(env(map[string]string{
		"SNIP_API_TOKEN": token,
		"SNIP_ADDR":      ":9000",
		"SNIP_DB_PATH":   "/var/lib/snip/x.db",
		"SNIP_BASE_URL":  "https://sn.ip/",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Addr != ":9000" || cfg.DBPath != "/var/lib/snip/x.db" || cfg.BaseURL != "https://sn.ip" {
		t.Fatalf("unexpected config: %+v", cfg)
	}
}

func TestErrors(t *testing.T) {
	cases := map[string]map[string]string{
		"missing token":    {},
		"short token":      {"SNIP_API_TOKEN": "short"},
		"whitespace token": {"SNIP_API_TOKEN": token + " x"},
		"bad addr":         {"SNIP_API_TOKEN": token, "SNIP_ADDR": "8080"},
		"bad base scheme":  {"SNIP_API_TOKEN": token, "SNIP_BASE_URL": "ftp://x"},
		"relative base":    {"SNIP_API_TOKEN": token, "SNIP_BASE_URL": "/foo"},
		"base with query":  {"SNIP_API_TOKEN": token, "SNIP_BASE_URL": "https://x/?a=b"},
	}
	for name, m := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := Load(env(m))
			if err == nil {
				t.Fatal("expected error")
			}
			if strings.Contains(err.Error(), token) {
				t.Fatal("error message must not echo the token")
			}
		})
	}
}
