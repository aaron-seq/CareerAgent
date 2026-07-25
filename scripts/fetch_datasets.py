"""
Download the real public datasets used for visa-sponsorship enrichment.

Sources are official, free, and bulk-downloadable:

* **UK** -- Home Office *Register of licensed sponsors: workers*. Published as
  a dated CSV on gov.uk; the landing page is scanned for the current file.
* **US** -- USCIS *H-1B Employer Data Hub* export.

Nothing is bundled with the repo: these files are large and their licences
generally do not permit redistribution. Run this once (and re-run periodically
-- the UK register is republished most working days).

    python -m scripts.fetch_datasets --uk
    python -m scripts.fetch_datasets --us --url <direct-csv-url>

If a source's URL has moved, pass ``--url`` explicitly rather than letting the
tool guess; a wrong file would silently poison the sponsor lookup.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent.parent / "core" / "enrichment" / "data"

UK_LANDING_PAGE = (
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
)
USCIS_HUB_PAGE = (
    "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub"
)

USER_AGENT = "CareerAgent/1.0 (+https://github.com/aaron-seq/CareerAgent)"


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=120.0, follow_redirects=True
    )


def find_uk_csv_url(client: httpx.Client) -> str:
    """Scrape the gov.uk landing page for the current register CSV link."""
    resp = client.get(UK_LANDING_PAGE)
    resp.raise_for_status()
    matches = re.findall(r'https://[^"\']+?\.csv', resp.text)
    if not matches:
        raise RuntimeError(
            "No CSV link found on the gov.uk landing page. The page layout may "
            f"have changed - open {UK_LANDING_PAGE} and pass --url directly."
        )
    # The register is the first CSV asset on the page.
    return matches[0]


def download(url: str, dest: Path, client: httpx.Client) -> int:
    """Stream a URL to disk. Returns bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    written = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
                written += len(chunk)
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded 0 bytes from {url}")
    tmp.replace(dest)
    return written


def verify(dest: Path) -> int:
    """Confirm the download parses and has a usable employer column."""
    from core.enrichment.visa import VisaSponsorFilter

    filt = VisaSponsorFilter.from_csv(dest)
    if not filt.loaded:
        raise RuntimeError(
            f"{dest} downloaded but produced no employer names. Check the file."
        )
    return len(filt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uk", action="store_true", help="UK sponsor register")
    parser.add_argument("--us", action="store_true", help="USCIS H-1B Data Hub")
    parser.add_argument("--url", help="Explicit CSV URL (overrides discovery)")
    parser.add_argument(
        "--out",
        help="Destination path (default: core/enrichment/data/visa_sponsors.csv)",
    )
    args = parser.parse_args(argv)

    if not (args.uk or args.us):
        parser.error("Choose a source: --uk and/or --us")

    dest = Path(args.out) if args.out else DATA_DIR / "visa_sponsors.csv"

    try:
        with _client() as client:
            if args.url:
                url = args.url
            elif args.uk:
                print(f"Locating current register on {UK_LANDING_PAGE} ...")
                url = find_uk_csv_url(client)
            else:
                parser.error(
                    "USCIS publishes per-year files behind a form; open "
                    f"{USCIS_HUB_PAGE}, then re-run with --url <direct-csv-url>."
                )
                return 2

            print(f"Downloading {url}")
            size = download(url, dest, client)
            count = verify(dest)
    except httpx.HTTPError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        print(
            "If this machine has no outbound access, download the file "
            "elsewhere and place it at the path above.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {dest} ({size:,} bytes, {count:,} employers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
