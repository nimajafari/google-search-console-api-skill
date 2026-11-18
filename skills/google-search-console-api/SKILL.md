---
name: google-search-console-api
description: Work with the Google Search Console API (searchconsole v1 / webmasters v3) — Search Analytics queries, URL Inspection, Sitemaps and Sites — while staying inside its quotas. Use when asked to "pull Search Console data", "export GSC performance data", "query clicks/impressions/CTR/position by page or query", "build a GSC pipeline or dashboard", "get more than 1,000 / 25,000 rows", "inspect URLs / check index status via API", "bulk URL inspection", "submit a sitemap via API", "list Search Console properties", set up OAuth or a service account for Search Console, or debug "quota exceeded", 403 or "User does not have sufficient permission" errors from the Search Console API.
license: MIT
metadata:
  author: nimajafari
  version: "0.1.0"
---

# Google Search Console API

The Search Console API is programmatic access to most of [Google Search Console](https://search.google.com/search-console/): the Performance report (Search Analytics), URL Inspection, Sitemaps, and the list of properties (Sites). It is a REST/JSON API. Every call needs OAuth 2.0 and a user (or service account) with Search Console permission on the property.

The hard part is not making a call. It is getting **complete, correct data without blowing the quota**. Most of this skill is about that.

## When to use this skill

- Extracting Performance data (clicks, impressions, CTR, position) for analysis, dashboards, warehousing, or SEO investigations.
- Checking index status, canonical selection, robots/noindex state, or rich-result validity for URLs at scale.
- Listing properties and permissions, listing or submitting sitemaps.
- Designing a scheduled sync job, or fixing one that hits `quotaExceeded`, misses rows, or returns numbers that don't match the UI.

**Not covered by this API:** the Page indexing (coverage) report, Links, Core Web Vitals, Crawl stats, Manual actions, removals, and the "Request indexing" button. For field Core Web Vitals use the CrUX API; for bulk raw Performance data on large sites use the Search Console **bulk data export to BigQuery**; the separate Indexing API only supports `JobPosting` / `BroadcastEvent` pages.

## The four services

| Service | Method | HTTP | Scope (min.) |
|---|---|---|---|
| Search Analytics | `searchanalytics.query` | `POST /webmasters/v3/sites/{siteUrl}/searchAnalytics/query` | `webmasters.readonly` |
| URL Inspection | `urlInspection.index.inspect` | `POST /v1/urlInspection/index:inspect` | `webmasters.readonly` |
| Sitemaps | `list` / `get` | `GET /webmasters/v3/sites/{siteUrl}/sitemaps[/{feedpath}]` | `webmasters.readonly` |
| Sitemaps | `submit` / `delete` | `PUT` / `DELETE …/sitemaps/{feedpath}` | `webmasters` |
| Sites | `list` / `get` | `GET /webmasters/v3/sites[/{siteUrl}]` | `webmasters.readonly` |
| Sites | `add` / `delete` | `PUT` / `DELETE /webmasters/v3/sites/{siteUrl}` | `webmasters` |

Root URL: `https://searchconsole.googleapis.com/` (current discovery doc, service `searchconsole` v1). The older `https://www.googleapis.com/webmasters/v3/...` paths still appear throughout Google's docs and still work for the `webmasters/v3` resources.

**Scopes:** `https://www.googleapis.com/auth/webmasters.readonly` (read-only) and `https://www.googleapis.com/auth/webmasters` (read/write). Request **read-only** unless the task really submits/deletes sitemaps or adds/removes sites.

### Property identifiers (`siteUrl`) — the #1 source of 403/404s

- **Domain property:** `sc-domain:example.com`
- **URL-prefix property:** `https://www.example.com/` — scheme, host and **trailing slash** must match exactly what is in Search Console.
- In paths, `siteUrl` and `feedpath` must be **fully URL-encoded** (`https%3A%2F%2Fwww.example.com%2F`, `sc-domain%3Aexample.com`). Client libraries do this for you; raw HTTP does not.
- Always start by calling `sites.list` and use a `siteUrl` **exactly as returned**. `siteUnverifiedUser` cannot read data.

## Quotas — read before writing any loop

Full detail and a budgeting worksheet: [references/LIMITS.md](references/LIMITS.md).

**Search Analytics**
- QPM limits: **1,200 QPM per site**, **1,200 QPM per user**, **40,000 QPM and 30,000,000 QPD per project**. Example: one user hitting 3 sites gets 1,200 QPM *combined*; two users on one site share 1,200 QPM.
- **Load quota** (the one that actually bites): internal cost of a query, tracked in **10-minute (short-term)** and **1-day (long-term)** windows. Cost rises with:
  - grouping/filtering by `page` or `query` (both together is the most expensive),
  - the **length of the date range** (6 months ≫ 1 day),
  - re-querying data you already have.
- Exceeding any of these returns the same **`quotaExceeded`** error. Short-term: wait **15 minutes** and retry. If a *single* query in a 10-minute window still fails, you're over the **long-term** (daily) load quota — reduce cost; retrying won't help until tomorrow.

**URL Inspection:** **2,000 QPD and 600 QPM per site**; 10,000,000 QPD and 15,000 QPM per project. 2,000 per day per property is the real ceiling — plan sampling, don't plan "inspect every URL".

**Everything else** (sites, sitemaps): 20 QPS and 200 QPM per user; 100,000,000 QPD per project.

**Batching does not save quota**: a batch of *n* calls counts as *n* requests. Batching only saves HTTP overhead. Current usage: Google Cloud console → APIs & Services → Search Console API → Quotas.

## Search Analytics: getting complete, correct data

Full request/response schema and recipes: [references/SEARCH-ANALYTICS.md](references/SEARCH-ANALYTICS.md).

### The recommended pattern (from Google's "all your data" guide)

1. **Probe freshness first.** Query the last ~10 days grouped by `date` only — no filters, no other dimensions. Days without data are simply absent. Final data is typically **2–3 days** behind.
2. **Query one day at a time** (`startDate == endDate`), once per day, for each `type` you need. A daily one-day query should not exceed your daily quota; a 16-month range grouped by page+query will.
3. **Page through results**: `rowLimit` max **25,000** (default **1,000**), increment `startRow` by 25,000 until a page returns **fewer rows than requested** or **0 rows**.
4. **Never re-pull finalized history.** Store it; only fetch new days (plus re-fetch recent non-final days if you use `dataState: "all"`).

```json
POST https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query
{
  "startDate": "2026-11-14",
  "endDate":   "2026-11-14",
  "dimensions": ["page", "query", "country", "device"],
  "type": "web",
  "rowLimit": 25000,
  "startRow": 0
}
```

### Hard data limits you must explain to stakeholders

- The API returns **top rows, not all rows**: at most **50,000 rows per day per search type** (sorted by clicks), regardless of paging.
- Grouping/filtering by `page` and/or `query` **drops some data** (to keep computation bounded) and anonymized rare queries are never returned. So **sum of rows < property total**. For accurate totals, query *without* `page`/`query` dimensions.
- Totals differ by **aggregation**: `byProperty` (de-duplicated per property) vs `byPage` (per canonical URL). If you group or filter by `page`, `byProperty` is not allowed — use `auto`.
- Dates are in **Pacific Time** (`America/Los_Angeles`), not UTC.
- Performance data retention in Search Console is about 16 months. Persist it if you need longer history.

### Correct metric math

- **CTR** of a group = `sum(clicks) / sum(impressions)`. Never average CTRs.
- **Position** of a group = impression-weighted: `sum(position × impressions) / sum(impressions)`. Never average positions.
- `position` is 1-based average topmost position; lower is better.

### Key request fields (quick reference)

- `dimensions`: `date`, `hour`, `query`, `page`, `country` (ISO 3166-1 alpha-3, lowercase in results, e.g. `usa`), `device` (`DESKTOP`/`MOBILE`/`TABLET`), `searchAppearance`, `brandedClassification`.
- `type`: `web` (default), `image`, `video`, `news` (News tab), `googleNews` (news.google.com + app), `discover`, `webMultimodal` (Lens / Circle to Search / image uploads). `searchType` is the deprecated alias.
- `dimensionFilterGroups[].filters[]`: `{dimension, operator, expression}`; operators `equals` (default, case-sensitive for page/query), `notEquals`, `contains`, `notContains`, `includingRegex`, `excludingRegex` (RE2). Groups are AND-ed; only `groupType: "and"` is supported.
- `dimensionFilterGroups[].filterLists[]`: multi-value exact match for `country` / `device` (`{"dimension":"country","expressions":["usa","can"]}`). Can't filter the same dimension in both `filters` and `filterLists`.
- `aggregationType`: `auto` (default), `byPage`, `byProperty` (not for `discover`/`googleNews`), `byNewsShowcasePanel`.
- `dataState`: `final` (default), `all` (includes fresh, not-yet-final data), `hourly_all` (required for the `hour` dimension; ~10 days available). The response `metadata.firstIncompleteDate` / `firstIncompleteHour` marks where numbers may still change.

### Gotchas

- **Search appearance is two-step**: query with `searchAppearance` as the *only* dimension to list types, then filter `searchAppearance equals <TYPE>` and add other dimensions — one query per type.
- **`brandedClassification`** (`BRANDED` / `NON_BRANDED`): `equals` only; can't be combined with a `query` filter in the same request; data from **2026-02-21** and only for top-level properties with enough volume.
- Results are sorted by **clicks desc**, except when grouped by `date` (date asc). Ties are arbitrary — don't rely on order for de-duplication.
- An out-of-range `startRow` returns **200 with zero rows**, not an error. Data exactly on a 25,000 boundary returns an empty next page.
- `rows` is **absent** (not `[]`) when there's no data.

## URL Inspection

Full schema, enums and a triage table: [references/URL-INSPECTION.md](references/URL-INSPECTION.md).

```json
POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect
{ "inspectionUrl": "https://www.example.com/page", "siteUrl": "sc-domain:example.com", "languageCode": "en-US" }
```

- Reports the **indexed** version only. It can't test a live URL, and it can't request indexing.
- `inspectionUrl` must be under `siteUrl`.
- Read `indexStatusResult`: `verdict` (PASS = valid, NEUTRAL = excluded, FAIL = error), `coverageState` (the human string, e.g. "Submitted and indexed"), `robotsTxtState`, `indexingState`, `pageFetchState`, `lastCrawlTime`, `googleCanonical` vs `userCanonical`, `crawledAs`.
- The most useful bulk signal is **`googleCanonical != userCanonical`** (Google chose a different canonical).
- `mobileUsabilityResult` is **deprecated**. `ampResult` / `richResultsResult` are absent when not applicable.
- **Budget:** 2,000/day/property. Prioritize a sample: top pages by clicks, recently changed templates, one URL per template/pattern, URLs from new sitemaps.

## Sites and Sitemaps

See [references/SITES-AND-SITEMAPS.md](references/SITES-AND-SITEMAPS.md). `sites.list` → `siteEntry[]` `{siteUrl, permissionLevel}` with `siteOwner` / `siteFullUser` / `siteRestrictedUser` / `siteUnverifiedUser`. `sitemaps.list` → `sitemap[]` with `path`, `lastSubmitted`, `lastDownloaded`, `isPending`, `isSitemapsIndex`, `type`, `errors`, `warnings`, `contents[].submitted` (`contents[].indexed` is deprecated — don't report it). `submit` / `delete` take no body and need the read/write scope. **These are writes. Confirm with the user before calling them.**

## Authentication and setup

Step by step, plus library install lines for every language: [references/AUTH-AND-SETUP.md](references/AUTH-AND-SETUP.md).

1. Create/choose a Google Cloud project → enable **Google Search Console API**.
2. Pick a credential:
   - **Installed/desktop OAuth client**: for a human running scripts locally; the user consents in a browser and you store the refresh token.
   - **Service account**: for unattended jobs. Then **add the service-account email as a user on the property** in Search Console (Settings → Users and permissions). Restricted is enough for reads; Owner/Full is needed for writes. Without this step every call returns 403.
   - API keys are **not** accepted for these resources; OAuth 2.0 is the only supported protocol.
3. Use a client library (recommended) — e.g. Python `google-api-python-client` with `build("searchconsole", "v1", credentials=creds)`, Node `googleapis` with `google.searchconsole("v1")`.

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

creds = service_account.Credentials.from_service_account_file(
    "sa.json", scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
gsc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

resp = gsc.searchanalytics().query(siteUrl="sc-domain:example.com", body={
    "startDate": "2026-11-14", "endDate": "2026-11-14",
    "dimensions": ["page"], "rowLimit": 25000, "startRow": 0,
}).execute()
rows = resp.get("rows", [])   # absent when empty
```

**Never** print, log or commit tokens, client secrets or service-account keys.

## Errors and retries

Full map: [references/ERRORS.md](references/ERRORS.md).

| Symptom | Cause | Action |
|---|---|---|
| 401 `authError` / `expired` | bad/expired token | refresh token; check scopes |
| 403 `insufficientPermissions` / "User does not have sufficient permission for site" | wrong `siteUrl` form, or the principal isn't a user on the property | `sites.list`, use exact `siteUrl`; add service account in Search Console |
| 403 `accessNotConfigured` | API not enabled on the project | enable Search Console API |
| 403/429 `rateLimitExceeded`, `userRateLimitExceeded` | QPS/QPM | exponential backoff with jitter |
| 403/429 `quotaExceeded` (Search Analytics) | load quota | wait 15 min once; if a lone query still fails → long-term load: shrink the date range or drop `page`/`query`, resume tomorrow |
| 400 `invalidParameter` / `badRequest` | bad enum, date order, mixed `filters`/`filterLists` on same dimension, `byProperty` with page | fix request; don't retry |
| 500 / 503 `backendError` | transient | backoff and retry (bounded) |

## Performance

[references/BATCH-AND-PERFORMANCE.md](references/BATCH-AND-PERFORMANCE.md): gzip (`Accept-Encoding: gzip` **and** a `User-Agent` containing `gzip`), partial responses via `fields=` (e.g. `fields=rows(keys,clicks,impressions)`), and HTTP batch (`multipart/mixed`, ≤ 1,000 calls, executed in any order, each call still counts against quota).

## The helper script

`scripts/gsc.py` is a single-file CLI using only the Python 3.9+ standard library. It writes progress to **stderr** and data to **stdout** (JSONL by default, or CSV/JSON). It paginates, splits ranges into one-day queries, throttles, backs off on rate limits, stops on load-quota errors, and keeps a per-property daily ledger for URL Inspection.

Token resolution order: `--token` / `GSC_ACCESS_TOKEN` → `google-auth` Application Default Credentials (if the package is installed; honours `GOOGLE_APPLICATION_CREDENTIALS` for service-account keys) → `gcloud auth application-default print-access-token`.

```bash
S=scripts/gsc.py
python3 $S sites                                                    # list properties + permission
python3 $S freshness sc-domain:example.com                          # last final day, incomplete days
python3 $S query sc-domain:example.com --start 2026-11-01 --end 2026-11-14 \
    --dimensions page,query --daily --format csv > gsc.csv          # 1 day per request, auto-paging
python3 $S query sc-domain:example.com --start 2026-11-14 --end 2026-11-14 \
    --dimensions query --filter "page:includingRegex:^https://www\.example\.com/blog/" \
    --filter-list country:usa,can --row-limit 100
python3 $S inspect sc-domain:example.com --file urls.txt            # summary JSONL, respects 2,000/day
python3 $S sitemaps sc-domain:example.com
python3 $S query ... --dry-run                                      # print the request, send nothing
```

Dates accept `YYYY-MM-DD`, `today`, `yesterday`, `today-N` or `Nd` (N days ago, Pacific Time). Exit codes: `0` ok, `1` API error, `2` usage error, `3` quota exhausted (rows already written are valid). Run `python3 scripts/gsc.py <command> --help` for every flag.

## Workflow for a data-pull task

1. `sites` → confirm the exact `siteUrl` and that permission isn't `siteUnverifiedUser`.
2. `freshness` → find the last final date. Don't request days that don't exist yet.
3. Design the **cheapest** query that answers the question: fewest dimensions, shortest range, no `page`+`query` unless needed. Totals → no page/query dimensions.
4. Estimate request count (days × types × pages of 25k) against the quotas above. For large backfills, spread the work over time.
5. Pull one day at a time, paginate, store raw rows with the request parameters (`type`, `dataState`, `aggregationType`) next to them.
6. Recompute CTR/position with the weighted formulas. State the data caveats (top-rows limit, anonymized queries, PT dates, `byPage` vs `byProperty`) when reporting numbers.

## Sources

- About: https://developers.google.com/webmaster-tools/about
- Usage limits: https://developers.google.com/webmaster-tools/limits
- Prerequisites: https://developers.google.com/webmaster-tools/v1/prereqs
- Client libraries: https://developers.google.com/webmaster-tools/v1/libraries
- Authorizing requests: https://developers.google.com/webmaster-tools/v1/how-tos/authorizing
- Performance tips: https://developers.google.com/webmaster-tools/v1/how-tos/performance
- Batch requests: https://developers.google.com/webmaster-tools/v1/how-tos/batch
- Search Analytics how-to: https://developers.google.com/webmaster-tools/v1/how-tos/search_analytics
- Query all your data: https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data
- API reference: https://developers.google.com/webmaster-tools/v1/api_reference_index
