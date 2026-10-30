# Enrichment datasets

**This directory ships without data on purpose.** Sponsor status, employer
ratings, and layoff history are facts about real, named companies. Shipping
invented values would put fabricated data in front of someone making career
decisions, so we don't — absent data is reported as *unknown*, never as a
negative.

Populate it with real data:

```bash
python -m scripts.fetch_datasets --uk   # Home Office register of licensed sponsors
python -m scripts.fetch_datasets --us --url "<direct-csv-url>"
```

For US data, choose a direct CSV download from the
[USCIS H-1B Employer Data Hub](https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub).
`--us` requires an explicit download URL; it does not discover one.
For updates, use `--out` with a new filename until
[#99](https://github.com/aaron-seq/CareerAgent/issues/99) is fixed: invalid
downloads can replace an existing dataset before validation.

Expected filenames (override with env vars):

| File | Env var | Contents |
|---|---|---|
| `visa_sponsors.csv` | `CAREERAGENT_VISA_DATASET` | Employer-name column; auto-detected across the official export formats. |
| `company_signals.csv` | `CAREERAGENT_COMPANY_DATASET` | `company_name` plus optional `glassdoor_rating`, `had_layoffs`. |

## Interpreting absence

- **UK register** is authoritative and complete: absence means the employer is
  genuinely not a licensed sponsor.
- **US H-1B / LCA data** is historical filing records: absence means "no
  recorded filings in the covered period", *not* that the employer will refuse
  to sponsor. The UI must not present it as a legal negative.

`company_signals.csv` has no official bulk source — supply it only from data you
are licensed to use. Glassdoor's terms prohibit scraping (see
`docs/RESEARCH.md`).

Downloaded datasets are gitignored: they are large and their licences generally
do not permit redistribution.
