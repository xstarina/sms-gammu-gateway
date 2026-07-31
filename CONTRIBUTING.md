# Contributing

Thanks for taking the time to look into this project. It is small, so the rules are short.

## Development environment

Everything runs in Docker — there is no local Python setup to prepare. Gammu and
`python-gammu` are compiled from source inside the image, so the first build takes a few
minutes; later ones are cached.

```bash
# Run the test suite
docker build --target test -t sms-gammu-gateway-test .
docker run --rm sms-gammu-gateway-test

# Build the runtime image
docker build -t sms-gammu-gateway .
```

The tests use a fake modem, so no device is needed to run them.

## Documentation is bilingual

`README.md` (English) and `README.ru.md` (Russian) are two views of the same document.

**Every change to one must be made to the other in the same commit.** The Russian file is a
full translation, not a summary: the same sections, examples and tables, in the same order.
Keep the language switcher at the top of both files.

CI enforces this in two ways — it compares the heading structure, the number of code blocks
and table rows, and it fails when one README is touched without the other. You can check
locally before pushing:

```bash
diff <(grep '^#' README.md | sed 's/ .*//') <(grep '^#' README.ru.md | sed 's/ .*//')
```

Empty output means the structure matches.

Other documents, including this one, are English only.

## Code style

- **English** for code, comments, docstrings, log and exception messages. The only Cyrillic
  in the repository is test data that deliberately exercises the non-Latin path.
- Comments explain **why**, not what. If a line needs a comment to say what it does, the line
  is usually the thing to fix.
- Match the surrounding code: single quotes, type hints on public functions, module-level
  docstrings.

## Tests

New behaviour needs a test. The suite lives in `tests/` and runs against `FakeModem` from
`tests/helpers.py`, which mirrors the interface of `sms_gateway.modem.Modem` — extend it when
you add a modem operation.

The conversation with the real device is not covered by tests and can only be verified against
connected hardware. Say so in the pull request if your change touches it.

## Commit messages

English, one summary line, then the reasoning if the change is not obvious. Explain why the
change is needed rather than restating the diff.

## What CI does

- `Docker` — runs the tests, then builds `linux/amd64` and `linux/arm64` on native runners and
  publishes a manifest list to `ghcr.io`. Publishing happens only for pushes to `main` and for
  tags; pull requests run the tests only.
- `Docs` — the README synchronisation checks described above.
