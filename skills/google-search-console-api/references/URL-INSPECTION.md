# URL Inspection: `urlInspection.index.inspect`

Sources: https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect and
https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult.

Equivalent to the URL Inspection tool in Search Console, **for the version in Google's index
only**. You can't test the live URL, and you can't request indexing through this API.

## Request

```
POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect
Scope: webmasters.readonly or webmasters
```

```json
{
  "inspectionUrl": "https://www.example.com/mypage",
  "siteUrl": "https://www.example.com/",
  "languageCode": "en-US"
}
```

| Field | Notes |
|---|---|
| `inspectionUrl` | Required. Fully-qualified URL, must be under `siteUrl`. |
| `siteUrl` | Required. Property as in Search Console; URL-prefix needs the trailing `/`; or `sc-domain:example.com`. Sent in the **body**, not URL-encoded. |
| `languageCode` | Optional BCP-47 for translated issue messages. Default `en-US`. |

**Quota:** 2,000/day and 600/min **per property**; 10M/day and 15k/min per project.

## Response: `inspectionResult`

```json
{
  "inspectionResult": {
    "inspectionResultLink": "https://search.google.com/search-console/inspect?...",
    "indexStatusResult":     { … },
    "ampResult":             { … },   // absent if not an AMP page
    "mobileUsabilityResult": { … },   // DEPRECATED
    "richResultsResult":     { … }    // absent if no rich results found
  }
}
```

### `indexStatusResult`

| Field | Meaning |
|---|---|
| `verdict` | `PASS` = Valid, `NEUTRAL` = Excluded, `FAIL` = Error/Invalid, `PARTIAL` (reserved, unused), `VERDICT_UNSPECIFIED` |
| `coverageState` | Human-readable status string, as in the UI (e.g. "Submitted and indexed", "Crawled - currently not indexed", "Duplicate, Google chose different canonical than user"). Group on it in reports. |
| `robotsTxtState` | `ALLOWED`, `DISALLOWED`, `ROBOTS_TXT_STATE_UNSPECIFIED` (not fetched, or robots.txt unreachable) |
| `indexingState` | `INDEXING_ALLOWED`, `BLOCKED_BY_META_TAG` (meta robots noindex), `BLOCKED_BY_HTTP_HEADER` (X-Robots-Tag noindex), `BLOCKED_BY_ROBOTS_TXT` (reserved, unused), `INDEXING_STATE_UNSPECIFIED` |
| `pageFetchState` | `SUCCESSFUL`, `SOFT_404`, `BLOCKED_ROBOTS_TXT`, `NOT_FOUND` (404), `ACCESS_DENIED` (401), `ACCESS_FORBIDDEN` (403), `BLOCKED_4XX`, `SERVER_ERROR` (5xx), `REDIRECT_ERROR`, `INTERNAL_CRAWL_ERROR`, `INVALID_URL`, `PAGE_FETCH_STATE_UNSPECIFIED` |
| `lastCrawlTime` | RFC 3339 UTC timestamp of the last crawl by the primary crawler. Absent if never crawled successfully. |
| `googleCanonical` | Canonical Google selected. Absent if not indexed. |
| `userCanonical` | Canonical the page declares. Absent if none declared. |
| `crawledAs` | `DESKTOP` / `MOBILE` (primary crawler). Absent if not crawled successfully. |
| `sitemap[]` | Sitemaps listing this URL, as known by Google. Not exhaustive. |
| `referringUrls[]` | URLs linking to it (directly or indirectly). |

### `ampResult`

`verdict`, `ampUrl`, `issues[] {issueMessage, severity: WARNING|ERROR}`, `robotsTxtState`,
`indexingState` (`AMP_INDEXING_ALLOWED`, `BLOCKED_DUE_TO_NOINDEX`,
`BLOCKED_DUE_TO_EXPIRED_UNAVAILABLE_AFTER`), `ampIndexStatusVerdict`, `lastCrawlTime`, `pageFetchState`.

### `richResultsResult`

`verdict`, `detectedItems[] { richResultType, items[] { name, issues[] { issueMessage, severity } } }`.
Items with an `ERROR` issue can't appear as rich results. Rich results that can't even be parsed
are not listed.

### `mobileUsabilityResult` (deprecated)

Kept for compatibility (`CONFIGURE_VIEWPORT`, `USE_LEGIBLE_FONT_SIZES`, `TAP_TARGETS_TOO_CLOSE`, …).
Google retired the mobile usability report in 2023. Don't build features on it.

## Triage table (what to tell the engineer)

| Signal | Likely cause | Next step |
|---|---|---|
| `pageFetchState` ≠ `SUCCESSFUL` | server/status problem when Google last crawled | check HTTP status and logs for Googlebot; fix, then wait for recrawl |
| `robotsTxtState = DISALLOWED` | robots.txt rule | fix robots.txt if the page should be indexed |
| `indexingState = BLOCKED_BY_*` | noindex (meta or header) | remove noindex if intended to rank |
| `googleCanonical != userCanonical` | Google picked another canonical (duplicate/near-duplicate, conflicting signals) | align canonical, internal links, sitemaps, redirects, hreflang |
| `verdict = NEUTRAL`, coverage "Crawled - currently not indexed" / "Discovered - currently not indexed" | quality/priority or crawl capacity | content quality, internal linking, crawl efficiency |
| `lastCrawlTime` old | low crawl priority | internal links, sitemap `lastmod`, server speed |
| `crawledAs = DESKTOP` on a mobile-first site | legacy desktop crawling | usually informational |
| `richResultsResult` items with `ERROR` | invalid structured data | fix required properties |

## Bulk inspection under 2,000/day/property

- **Sample, don't enumerate**: top N pages by clicks (from Search Analytics), one or two URLs per
  template/route pattern, recently deployed or changed URLs, URLs from a newly submitted sitemap,
  and pages that lost clicks.
- **Persist results with a timestamp** and re-inspect only on change. Index state changes slowly.
- **Throttle** (≤ 600/min/property; ~1/s is plenty) and **keep a per-property daily counter**
  that resets at midnight PT. `scripts/gsc.py inspect` does both.
- Several properties (e.g. URL-prefix properties for subfolders, verified separately) each get
  their own 2,000/day. That's a legitimate way to cover more of a very large site, as long as each
  URL is inspected under a property that contains it.

## Python

```python
res = gsc.urlInspection().index().inspect(body={
    "inspectionUrl": "https://www.example.com/page",
    "siteUrl": "sc-domain:example.com",
}).execute()["inspectionResult"]["indexStatusResult"]
mismatch = res.get("googleCanonical") and res.get("userCanonical") \
           and res["googleCanonical"] != res["userCanonical"]
```
