package server

import (
	"crypto/rand"
	"errors"
	"net/url"
	"regexp"
	"strings"
)

const (
	maxURLLength      = 2048
	generatedSlugLen  = 10
	slugAlphabet      = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
	maxRequestBodyLen = 16 << 10
)

var slugPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{3,32}$`)

// reservedSlugs would be shadowed by (or confusable with) service routes.
var reservedSlugs = map[string]bool{
	"api":     true,
	"healthz": true,
}

func validateSlug(slug string) error {
	if !slugPattern.MatchString(slug) {
		return errors.New("slug must be 3-32 characters of A-Z, a-z, 0-9, '_' or '-'")
	}
	if reservedSlugs[strings.ToLower(slug)] {
		return errors.New("slug is reserved")
	}
	return nil
}

// validateURL accepts only absolute http(s) URLs with a host, up to maxURLLength.
func validateURL(raw string) error {
	if raw == "" {
		return errors.New("url is required")
	}
	if len(raw) > maxURLLength {
		return errors.New("url must be at most 2048 characters")
	}
	for _, r := range raw {
		if r <= 0x20 || r == 0x7f {
			return errors.New("url must not contain whitespace or control characters")
		}
	}
	u, err := url.Parse(raw)
	if err != nil {
		return errors.New("url is not valid")
	}
	if !u.IsAbs() || (u.Scheme != "http" && u.Scheme != "https") {
		return errors.New("url must be an absolute http or https URL")
	}
	if u.Hostname() == "" {
		return errors.New("url must include a host")
	}
	if u.User != nil {
		// user:pass@host URLs are a common phishing trick and leak credentials.
		return errors.New("url must not contain credentials")
	}
	return nil
}

// randomSlug returns an unbiased random slug drawn from slugAlphabet using
// crypto/rand. The alphabet omits look-alike characters (0/O, 1/l/I).
func randomSlug() (string, error) {
	const n = len(slugAlphabet)
	// Reject bytes >= limit so every alphabet character is equally likely.
	limit := byte(256 - 256%n)
	out := make([]byte, 0, generatedSlugLen)
	buf := make([]byte, generatedSlugLen*2)
	for len(out) < generatedSlugLen {
		if _, err := rand.Read(buf); err != nil {
			return "", err
		}
		for _, b := range buf {
			if b >= limit {
				continue
			}
			out = append(out, slugAlphabet[int(b)%n])
			if len(out) == generatedSlugLen {
				break
			}
		}
	}
	return string(out), nil
}
