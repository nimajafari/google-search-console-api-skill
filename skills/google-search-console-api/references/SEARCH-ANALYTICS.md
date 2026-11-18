# Search Analytics: `searchanalytics.query`

Sources: https://developers.google.com/webmaster-tools/v1/searchanalytics/query,
https://developers.google.com/webmaster-tools/v1/how-tos/search_analytics,
https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data, and the `searchconsole`
v1 discovery document.

Exposes the data in the Search Console **Performance** report. Read Google's
[Performance report help](https://support.google.com/webmasters/answer/6155685) for exactly how
clicks, impressions and position are counted.

## Request

```
POST https://searchconsole.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query
Scope: webmasters.readonly or webmasters
```

`siteUrl` (path, URL-encoded): `https://www.example.com/` (URL-prefix) or `sc-domain:example.com` (Domain).

```json
{
  "startDate": "YYYY-MM-DD",
  "endDate": "YYYY-MM-DD",
  "dimensions": ["string"],
  "type": "string",
  "dimensionFilterGroups": [{
    "groupType": "and",
    "filters":     [{ "dimension": "string", "operator": "string", "expression": "string" }],
    "filterLists": [{ "dimension": "string", "expressions": ["string"] }]
  }],
  "aggregationType": "string",
  "rowLimit": 1000,
  "startRow": 0,
  "dataState": "string"
}
```

| Field | Required | Notes |
|---|---|---|
| `startDate` / `endDate` | yes | `YYYY-MM-DD` in **PT** (UTC-7/-8). Inclusive. `start ≤ end`. |
| `dimensions[]` | no | Group-by keys, in order. No dimensions → one total row. Any number, no repeats. |
| `type` | no | `web` (default), `image`, `video`, `news`, `googleNews`, `discover`, `webMultimodal`. (`searchType` = deprecated alias.) |
| `dimensionFilterGroups[]` | no | All groups must match (AND). |
| `…groupType` | no | Only `"and"` is supported. |
| `…filters[]` | no | Single-value filter. Expression max length 4,096 chars. |
| `…filterLists[]` | no | Multi-value exact match, `country` or `device` only. Not combinable with `filters` on the same dimension. |
| `aggregationType` | no | `auto` (default), `byPage`, `byProperty`, `byNewsShowcasePanel`. |
| `rowLimit` | no | 1–25,000. Default **1,000**. |
| `startRow` | no | Zero-based, default 0. Past the end → 200 OK with zero rows. |
| `dataState` | no | `final` (default), `all`, `hourly_all`. Case-insensitive. |

### Dimensions

| Dimension | Value format |
|---|---|
| `date` | `YYYY-MM-DD` (PT) |
| `hour` | `YYYY-MM-DDThh:mm:ss±hh:mm` (PT). Requires `dataState: "hourly_all"`. About 10 days available. |
| `query` | query string |
| `page` | URL string (canonical URL when aggregated by page) |
| `country` | ISO 3166-1 alpha-3, lowercase in results (`usa`, `ind`, `mdv`) |
| `device` | `DESKTOP`, `MOBILE`, `TABLET` |
| `searchAppearance` | e.g. `AMP_BLUE_LINK`, `INSTANT_APP`, … (list them first; see below) |
| `brandedClassification` | `BRANDED`, `NON_BRANDED` |

### Filter operators

| Operator | Semantics |
|---|---|
| `equals` (default) | exact match. **Case-sensitive** for `page` and `query`. |
| `notEquals` | not exact match. Case-sensitive for `page`/`query`. |
| `contains` | contains or equals, case-insensitive |
| `notContains` | doesn't contain, case-insensitive |
| `includingRegex` | must match [RE2](https://github.com/google/re2/wiki/Syntax) regex |
| `excludingRegex` | must not match RE2 regex |

Filterable dimensions: `country`, `device`, `page`, `query`, `searchAppearance`, `brandedClassification`.
You can filter on a dimension without grouping by it.

`brandedClassification` constraints: only `equals`; can't be combined with a `query` filter in the
same request; data only from **February 21, 2026**, only for top-level properties with sufficient
query and impression volume.

### Aggregation

- `byProperty`: all data for the property aggregated (a result counted once per property).
- `byPage`: aggregated by canonical URI.
- If you **group or filter by page**, use `auto` (`byProperty` is an error).
- `byProperty` is not supported for `type=discover` / `googleNews`.
- `byNewsShowcasePanel` requires a `searchAppearance = NEWS_SHOWCASE` filter and `type` of
  `discover` or `googleNews`. You can't group/filter by page with it.
- If you request something other than `auto` and it's invalid, you get an **error**. The API never
  silently changes your aggregation.

## Response

```json
{
  "rows": [{ "keys": ["…"], "clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0 }],
  "responseAggregationType": "auto | byPage | byProperty",
  "metadata": { "firstIncompleteDate": "YYYY-MM-DD", "firstIncompleteHour": "YYYY-MM-DDThh:mm:ss±hh:mm" }
}
```

- `rows[].keys[]` follow the order of `dimensions`.
- `ctr` is 0–1. `position` is average position.
- Sorted by clicks desc; when grouped by `date`, date asc. Ties are arbitrary.
- When grouped by `date`, days without data are **omitted**.
- `rows` is **missing** when nothing matches. Treat it as `[]`.
- `metadata` appears only for `dataState: all` (grouped by date → `firstIncompleteDate`) or
  `hourly_all` (grouped by hour → `firstIncompleteHour`), and only when the range contains
  incomplete data. Everything at/after that point may still change. (The reference page spells
  these `first_incomplete_date` / `first_incomplete_hour`; the JSON uses camelCase. Read both
  defensively.) Times are America/Los_Angeles.

## Why your numbers don't match the UI (or each other)

1. **Top rows only**: the method doesn't guarantee all rows, and caps at 50,000 rows/day/search type.
2. **Data loss with detail**: grouping by `page` and/or `query` may drop data so it can compute in reasonable time.
3. **Anonymized queries**: rare queries are hidden for privacy, so query-level sums < totals.
4. **Aggregation**: `byProperty` vs `byPage` count impressions/clicks/position differently
   ([help](https://support.google.com/webmasters/answer/7576553#urlorsite)).
5. **`type`**: the UI's default is Web. Discover and Google News are separate types, not part of `web`.
6. **`dataState`**: the UI shows fresh data. The API default is `final` only.
7. **Time zone**: dates are PT.
8. **Wrong math**: CTR and position must be recomputed from sums (`Σclicks/Σimpr`, `Σ(pos·impr)/Σimpr`).

For **accurate totals**, omit `page` and `query`:

```json
{ "startDate": "2026-11-14", "endDate": "2026-11-14", "dimensions": ["country","device"], "type": "web" }
```

For **detail** (accepting some loss):

```json
{ "startDate": "2026-11-14", "endDate": "2026-11-14", "dimensions": ["page","query","country","device"], "type": "web" }
```

## Recipes

**Freshness probe**: last 10 days, `dimensions: ["date"]`, nothing else. The last date returned is
the last day with data. Add `dataState: "all"` to see fresh days and `metadata.firstIncompleteDate`.

**Top 10 queries**: `dimensions: ["query"], rowLimit: 10`.

**Top 10 pages**: `dimensions: ["page"], rowLimit: 10`.

**Top queries in India on mobile** (`equals` is default, so `operator` can be omitted):

```json
{ "dimensions": ["query"], "rowLimit": 10,
  "dimensionFilterGroups": [{ "filters": [
    { "dimension": "country", "expression": "ind" },
    { "dimension": "device",  "expression": "MOBILE" } ] }] }
```

**Rows 11–20**: `rowLimit: 10, startRow: 10`.

**Section of a site**: `{ "dimension": "page", "operator": "includingRegex", "expression": "^https://www\\.example\\.com/blog/" }`.

**Several countries at once**: `"filterLists": [{ "dimension": "country", "expressions": ["usa","can","gbr"] }]`.

**Brand vs non-brand trend**: `dimensions: ["date","brandedClassification"]` (no `query` filter).

**Hourly**: `dimensions: ["hour"], dataState: "hourly_all"`, range within the last ~10 days.

**Search appearance (two-step)**:

```json
// 1) list types: searchAppearance must be the ONLY dimension
{ "startDate": "2026-10-01", "endDate": "2026-10-31", "type": "web", "dimensions": ["searchAppearance"] }
// 2) one query per type found
{ "startDate": "2026-10-01", "endDate": "2026-10-31", "type": "web", "dimensions": ["device"],
  "dimensionFilterGroups": [{ "filters": [
    { "dimension": "searchAppearance", "operator": "equals", "expression": "AMP_BLUE_LINK" } ] }] }
```

## Paging loop (from Google's pseudocode)

```
maxRows = 25000; i = 0
do:
    response = query(startDate = D, endDate = D, dimensions…, type…,
                     rowLimit = maxRows, startRow = i * maxRows)
    i++
    store(response.rows)
while len(response.rows) == maxRows     # Google's pseudocode loops until 0 rows; stopping on a short page saves one call
```

Run it once per day `D` (typically D = 3 days ago) per `type` you need.

## Client library snippets

Python (`google-api-python-client`):

```python
def fetch_day(gsc, site, day, dimensions, search_type="web"):
    out, start = [], 0
    while True:
        body = {"startDate": day, "endDate": day, "dimensions": dimensions,
                "type": search_type, "rowLimit": 25000, "startRow": start}
        rows = gsc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
        out.extend(rows)
        if len(rows) < 25000:
            return out
        start += 25000
```

Node (`googleapis`):

```js
import { google } from 'googleapis';
const auth = new google.auth.GoogleAuth({ scopes: ['https://www.googleapis.com/auth/webmasters.readonly'] });
const gsc = google.searchconsole({ version: 'v1', auth });
const { data } = await gsc.searchanalytics.query({
  siteUrl: 'sc-domain:example.com',
  requestBody: { startDate: '2026-11-14', endDate: '2026-11-14', dimensions: ['page'], rowLimit: 25000 },
});
const rows = data.rows ?? [];
```
