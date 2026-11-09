.PHONY: build test run vet fmt

build:
	go build -o bin/snip ./cmd/snip

test:
	go test ./...

vet:
	go vet ./...

fmt:
	gofmt -l -w .

# Requires SNIP_API_TOKEN to be set in the environment.
run:
	go run ./cmd/snip
