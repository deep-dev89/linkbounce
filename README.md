# linkbounce

A small, dependency-light Python script that checks a list of URLs to see
whether visiting them **redirects you to a different page**, and flags
redirected links as **invalid** (or valid, if you flip the logic). Built
for Linux (cron / systemd timers), but it's plain Python 3 + `requests`,
so it runs anywhere.

## Why

Sometimes you have a list of links and just want to know: does this URL
still go where it's supposed to, or has it started bouncing somewhere
else (a login page, a "moved" notice, an error page, a completely
different domain)? `linkbounce` visits each URL, follows any redirect
chain, and reports whether the final destination differs from where you
started.

## Features

- Reads URLs from a file, the command line, or both
- Follows the full redirect chain and reports the final URL + hop count
- Fine-grained control over what counts as "the same page": ignore
  scheme, `www.`, trailing slashes, query strings, or compare domains only
- Invert the logic: a redirect can mean valid *or* invalid (handy for
  checking that short links / forwarders actually redirect)
- Concurrent requests (configurable worker count)
- Configurable timeout, User-Agent, and SSL verification
- Output as plain text, CSV, or JSON — to stdout or a file
- Optional non-zero exit code on any invalid result, for cron/CI use

## Requirements

- Python 3.7+
- `requests`

```bash
pip install requests --break-system-packages
```

(Drop `--break-system-packages` if you're using a virtualenv.)

## Installation

```bash
git clone https://github.com/deep-dev89/linkbounce.git
cd linkbounce
chmod +x linkbounce.py
```

## Usage

```bash
./linkbounce.py -f urls.txt
```

By default, a URL that redirects to a different page is marked
**invalid**. Add `--invert` if a redirect should mean the page is
**valid** instead.

### Common examples

Pass URLs directly instead of a file:

```bash
./linkbounce.py -u https://example.com https://example.org
```

Ignore harmless differences so `http://` vs `https://`, `www.` vs no
`www.`, and trailing slashes don't count as a "real" redirect:

```bash
./linkbounce.py -f urls.txt --ignore-scheme --ignore-www --ignore-trailing-slash
```

Only flag it as a redirect if the domain itself changes (ignore
path/query changes entirely):

```bash
./linkbounce.py -f urls.txt --domain-only
```

Invert logic — useful for checking that short links / forwarders are
still working (a redirect is the expected, "valid" outcome):

```bash
./linkbounce.py -f urls.txt --invert
```

Save results as CSV, use 20 concurrent workers, 15s timeout:

```bash
./linkbounce.py -f urls.txt -o results.csv --format csv -w 20 -t 15
```

By default, only **valid** links (no redirect) are shown/written. To see
the ones that redirected instead, or everything:

```bash
./linkbounce.py -f urls.txt --show invalid
./linkbounce.py -f urls.txt --show all
```

Use in a cron job / CI and fail loudly if anything's invalid:

```bash
./linkbounce.py -f urls.txt --fail-on-invalid
```

## Options

| Flag | Description |
|---|---|
| `-f, --urls-file` | Path to a text file with one URL per line |
| `-u, --urls` | One or more URLs given directly |
| `--invert` | A redirect means VALID instead of INVALID |
| `--ignore-scheme` | Treat `http://` and `https://` as equivalent |
| `--ignore-www` | Treat `www.example.com` and `example.com` as equivalent |
| `--ignore-trailing-slash` | Treat `/path` and `/path/` as equivalent |
| `--ignore-query` | Ignore query string differences when comparing |
| `--domain-only` | Only flag as a redirect if the domain itself changes |
| `-o, --output` | Write results to a file instead of stdout |
| `--format` | `text` (default), `csv`, or `json` |
| `-w, --workers` | Number of concurrent requests (default: 10) |
| `-t, --timeout` | Per-request timeout in seconds (default: 10) |
| `--user-agent` | Custom User-Agent header |
| `--no-verify-ssl` | Disable SSL certificate verification |
| `--show` | Which results to show/write: `valid` (default), `invalid`, or `all` |
| `--fail-on-invalid` | Exit code 1 if any URL is invalid |
| `-q, --quiet` | Suppress the progress output on stderr |

## How "redirected" is determined

`linkbounce` requests each URL with redirects followed automatically,
then compares the URL you gave it against the final URL the server
landed on (after normalizing both, based on whichever `--ignore-*` flags
you passed). If they differ, it counts as a redirect.

## Limitations

- Like most HTTP-based checkers, this only sees server-side redirects
  (HTTP 3xx responses) and normal `Location` header chains — it doesn't
  execute JavaScript, so a client-side/meta-refresh redirect done purely
  via JS won't be detected.
- A `--max-redirects` safety limit is enforced by the underlying
  `requests` library; an extremely long redirect chain will surface as
  an error in the results rather than a silent failure.

## License

MIT — see [LICENSE](LICENSE).
