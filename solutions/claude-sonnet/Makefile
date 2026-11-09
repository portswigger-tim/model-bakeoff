.PHONY: build test run
build:
	go build -o bin/snip ./cmd/snip
test:
	go vet ./... && go test -race -count=1 ./...
run:
	go run ./cmd/snip
