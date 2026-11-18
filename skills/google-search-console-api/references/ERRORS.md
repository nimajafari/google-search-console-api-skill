# Errors and how to handle them

Source: https://developers.google.com/webmaster-tools/v1/errors (global Google API error domain),
plus the Search Console limits page.

## Error shape

Classic (`webmasters/v3`) format:

```json
{
  "error": {
    "errors": [{ "domain": "global", "reason": "invalidParameter",
                 "message": "…", "locationType": "parameter", "location": "…" }],
    "code": 400,
    "message": "…"
  }
}
```

Endpoints served from `searchconsole.googleapis.com` may return the newer format with
`"status": "PERMISSION_DENIED" | "RESOURCE_EXHAUSTED" | "INVALID_ARGUMENT"` and
`error.details[]` instead of `error.errors[]`. **Classify on HTTP code + reason/status + message**,
not on one field.

## Decision table

| HTTP | reason / status | Meaning | Retry? |
|---|---|---|---|
| 400 | `badRequest`, `invalid`, `invalidParameter`, `required`, `parseError` / `INVALID_ARGUMENT` | bad request: date format/order, bad enum, `rowLimit` > 25,000, `byProperty` with page, same dimension in `filters` and `filterLists`, `brandedClassification` with a `query` filter, `inspectionUrl` not under `siteUrl` | **No.** Fix the request. |
| 401 | `authError`, `expired`, `required`, `unauthorized` / `UNAUTHENTICATED` | missing/expired/invalid token | Refresh once, then fail |
| 403 | `insufficientPermissions` / `PERMISSION_DENIED` ("User does not have sufficient permission for site …") | wrong `siteUrl` form (`sc-domain:` vs URL-prefix, http vs https, missing trailing slash, not URL-encoded), principal not added in Search Console, `siteUnverifiedUser`, or a write with read-only scope | **No.** Run `sites.list` with the same credentials. |
| 403 | `accessNotConfigured` | Search Console API not enabled on the project (or project blocked) | No. Enable the API. |
| 403 | `forbidden` | operation not allowed | No |
| 403 / 429 | `rateLimitExceeded`, `userRateLimitExceeded`, `concurrentLimitExceeded` / `RESOURCE_EXHAUSTED` | QPS/QPM | **Yes**, exponential backoff + jitter |
| 403 / 429 | `quotaExceeded`, `dailyLimitExceeded` | Search Analytics **load** quota, or a daily quota | See below |
| 404 | `notFound` | unknown sitemap/site path, or bad encoding of `siteUrl`/`feedpath` | No |
| 413 | `batchSizeTooLarge` | > 1,000 calls in a batch | Split |
| 500 | `internalError` | transient | Yes (bounded) |
| 503 | `backendError`, `backendNotConnected`, `notReady` | transient | Yes (bounded) |

### `quotaExceeded` from Search Analytics

All Search Analytics quota events return the same error, so you need to know which quota it was.

1. Wait **15 minutes**, retry the same query **once**.
2. Still failing with only that one query in a 10-minute window → **long-term (daily) load quota**.
   Stop and:
   - shorten the date range (one day per query),
   - remove `page` and/or `query` grouping/filtering where possible (page+query is the most expensive),
   - stop re-pulling data you already have,
   - resume after the daily window resets.
3. If you're only over short-term quota, spread queries out over the day (lower concurrency, add sleeps).

### URL Inspection quota

2,000/day/property. When you hit it, stop for that property until the next PT day. Persist which
URLs are done so the next run resumes where it stopped.

## Backoff template (Python)

```python
import random, time
from googleapiclient.errors import HttpError

RETRY_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "concurrentLimitExceeded",
                 "backendError", "internalError"}

def call_with_backoff(req, max_attempts=6):
    for attempt in range(max_attempts):
        try:
            return req.execute()
        except HttpError as e:
            text = (e.content or b"").decode("utf-8", "replace")
            if "quotaExceeded" in text or "dailyLimitExceeded" in text:
                raise                       # load/daily quota: handle at the job level (15-min wait or stop)
            if e.resp.status in (429, 500, 503) or any(r in text for r in RETRY_REASONS):
                time.sleep(min(64, 2 ** attempt) + random.random())
                continue
            raise
    raise RuntimeError("gave up after retries")
```

`google-api-python-client` also retries on its own via `execute(num_retries=N)` for 5xx/429.
