#!/usr/bin/env python3
"""
linkbounce.py

Goes through a list of URLs and checks whether visiting them redirects you
to a different page. URLs that redirect can be flagged as "invalid" (the
default), or you can flip that logic with --invert so a redirect counts
as "valid".

Designed to run on Linux (cron / systemd timer friendly), but works
anywhere Python 3 + requests run.

USAGE
-----
    # Basic: read URLs from a file, one per line
    ./linkbounce.py -f urls.txt

    # URLs passed directly on the command line
    ./linkbounce.py -u https://example.com https://example.org

    # Ignore harmless differences (http->https, trailing slash, www.) when
    # deciding whether a "redirect" actually counts as one
    ./linkbounce.py -f urls.txt --ignore-scheme --ignore-www --ignore-trailing-slash

    # Only flag it as a redirect if the domain itself changes
    ./linkbounce.py -f urls.txt --domain-only

    # Invert logic: a redirect means the page IS valid (e.g. checking that
    # short links actually forward somewhere)
    ./linkbounce.py -f urls.txt --invert

    # Save results as CSV, use 20 concurrent workers, custom timeout
    ./linkbounce.py -f urls.txt -o results.csv --format csv -w 20 -t 15

    # By default, only VALID links (i.e. no redirect) are shown/written.
    # To see the ones that redirected instead, or everything:
    ./linkbounce.py -f urls.txt --show invalid
    ./linkbounce.py -f urls.txt --show all

EXIT CODE
---------
    0  -> ran fine (even if some/all URLs came back invalid)
    1  -> ran fine, but at least one URL was invalid, and --fail-on-invalid was set
    2  -> bad usage / no URLs supplied

Dependencies: requests  (pip install requests --break-system-packages)
"""

import argparse
import concurrent.futures
import csv
import json
import sys
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import requests
except ImportError:
    print(
        "This script requires the 'requests' library.\n"
        "Install it with: pip install requests --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(2)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 linkbounce/1.0"
)


@dataclass
class Result:
    url: str
    final_url: Optional[str]
    status_code: Optional[int]
    redirect_count: int
    redirected: bool
    valid: bool
    error: Optional[str] = None

    def to_row(self):
        return asdict(self)


def load_urls(args) -> list:
    urls = []

    if args.urls_file:
        try:
            with open(args.urls_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        except OSError as e:
            print(f"Could not read urls file '{args.urls_file}': {e}", file=sys.stderr)
            sys.exit(2)

    if args.urls:
        urls.extend(args.urls)

    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped


def normalize(url: str, args) -> str:
    """Normalize a URL for comparison purposes based on the --ignore-* flags."""
    parts = urlsplit(url)

    scheme = parts.scheme
    netloc = parts.netloc
    path = parts.path
    query = parts.query
    fragment = ""  # fragments never affect what the server sends, always ignore

    if args.ignore_scheme:
        scheme = "http"

    if args.ignore_www:
        netloc = netloc[4:] if netloc.lower().startswith("www.") else netloc

    if args.domain_only:
        # Only compare the host, blow away path/query for the comparison
        path, query = "", ""

    if args.ignore_trailing_slash:
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")

    if args.ignore_query:
        query = ""

    return urlunsplit((scheme, netloc.lower(), path, query, fragment))


def check_url(url: str, args, timeout: int, user_agent: str, verify_ssl: bool) -> Result:
    headers = {"User-Agent": user_agent}
    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
            allow_redirects=True,
        )

        final_url = resp.url
        redirect_count = len(resp.history)

        original_norm = normalize(url, args)
        final_norm = normalize(final_url, args)

        redirected = (redirect_count > 0) and (original_norm != final_norm)

        # Default: redirecting to a different page marks it INVALID.
        # --invert flips that: redirecting marks it VALID.
        valid = (not redirected) if not args.invert else redirected

        return Result(
            url=url,
            final_url=final_url,
            status_code=resp.status_code,
            redirect_count=redirect_count,
            redirected=redirected,
            valid=valid,
        )

    except requests.exceptions.TooManyRedirects as e:
        return Result(
            url=url, final_url=None, status_code=None, redirect_count=-1,
            redirected=True, valid=(args.invert), error=f"Too many redirects: {e}",
        )

    except requests.exceptions.RequestException as e:
        return Result(
            url=url, final_url=None, status_code=None, redirect_count=0,
            redirected=False, valid=False, error=str(e),
        )


def write_output(results, args):
    if args.format == "csv":
        target = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
        writer = csv.writer(target)
        writer.writerow(["url", "final_url", "status_code", "redirect_count", "redirected", "valid", "error"])
        for r in results:
            writer.writerow([r.url, r.final_url, r.status_code, r.redirect_count,
                              r.redirected, r.valid, r.error or ""])
        if args.output:
            target.close()

    elif args.format == "json":
        data = [r.to_row() for r in results]
        text = json.dumps(data, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        else:
            print(text)

    else:  # plain text
        lines = []
        for r in results:
            status = "VALID" if r.valid else "INVALID"
            if r.error:
                extra = f" [error: {r.error}]"
            elif r.redirected:
                extra = f" -> {r.final_url} ({r.redirect_count} hop{'s' if r.redirect_count != 1 else ''}, HTTP {r.status_code})"
            else:
                extra = f" (no redirect, HTTP {r.status_code})"
            lines.append(f"{status}\t{r.url}{extra}")
        text = "\n".join(lines)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        else:
            print(text)


def main():
    parser = argparse.ArgumentParser(
        description="Check a list of URLs to see whether they redirect to a different page, "
                    "flagging redirects as invalid links (or valid, with --invert).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-f", "--urls-file", help="Path to a text file with one URL per line")
    parser.add_argument("-u", "--urls", nargs="+", help="One or more URLs given directly")
    parser.add_argument("--invert", action="store_true",
                        help="Flip the logic: a redirect means the page is VALID "
                             "(default: a redirect means INVALID)")
    parser.add_argument("--ignore-scheme", action="store_true",
                        help="Treat http:// and https:// as equivalent when comparing")
    parser.add_argument("--ignore-www", action="store_true",
                        help="Treat 'www.example.com' and 'example.com' as equivalent")
    parser.add_argument("--ignore-trailing-slash", action="store_true",
                        help="Treat '/path' and '/path/' as equivalent")
    parser.add_argument("--ignore-query", action="store_true",
                        help="Ignore query string differences when comparing")
    parser.add_argument("--domain-only", action="store_true",
                        help="Only flag as a redirect if the domain itself changes "
                             "(ignores path/query entirely)")
    parser.add_argument("-o", "--output", help="Write results to this file instead of stdout")
    parser.add_argument("--format", choices=["text", "csv", "json"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("-w", "--workers", type=int, default=10,
                        help="Number of concurrent requests (default: 10)")
    parser.add_argument("-t", "--timeout", type=int, default=10,
                        help="Per-request timeout in seconds (default: 10)")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                        help="Custom User-Agent header")
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="Disable SSL certificate verification")
    parser.add_argument("--show", choices=["valid", "invalid", "all"], default="valid",
                        help="Which results to show/write: 'valid' (default), "
                             "'invalid', or 'all'")
    parser.add_argument("--fail-on-invalid", action="store_true",
                        help="Exit with code 1 if any URL is invalid (useful in CI/cron)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress the progress summary printed to stderr")

    args = parser.parse_args()

    urls = load_urls(args)
    if not urls:
        print("No URLs provided. Use -f/--urls-file and/or -u/--urls.", file=sys.stderr)
        sys.exit(2)

    if args.no_verify_ssl:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    verify_ssl = not args.no_verify_ssl

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_url = {
            executor.submit(check_url, url, args, args.timeout, args.user_agent, verify_ssl): url
            for url in urls
        }
        done = 0
        for future in concurrent.futures.as_completed(future_to_url):
            results.append(future.result())
            done += 1
            if not args.quiet:
                print(f"\rChecked {done}/{len(urls)}", end="", file=sys.stderr, flush=True)

    if not args.quiet:
        print("", file=sys.stderr)

    order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: order.get(r.url, 0))

    invalid_count = sum(1 for r in results if not r.valid)
    total_checked = len(results)

    if args.show == "valid":
        shown = [r for r in results if r.valid]
    elif args.show == "invalid":
        shown = [r for r in results if not r.valid]
    else:
        shown = results

    write_output(shown, args)

    if not args.quiet:
        print(f"Done. {invalid_count} invalid / {total_checked} checked "
              f"({len(shown)} shown, --show={args.show}).", file=sys.stderr)

    if args.fail_on_invalid and invalid_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
