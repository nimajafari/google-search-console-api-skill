# Search Console API usage limits

Source: https://developers.google.com/webmaster-tools/limits (last updated 2025-08-28) and
https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data. Re-check the source
before quoting numbers to a stakeholder; Google can change quotas without a version bump.

## The numbers

### Search Analytics (`searchanalytics.query`)

Two independent families of limits. Exceeding **any** of them returns the same
[`quotaExceeded`](https://developers.google.com/webmaster-tools/v1/errors#error_quotaExceeded) error.

**Rate (QPS / QPM / QPD) limits**

| Scope | What it counts | Limit |
|---|---|---|
| Per site | calls querying the same property | **1,200 QPM** |
| Per user | calls made by the same user (or service account) | **1,200 QPM** |
| Per project | calls made with the same Cloud project / Developer Console key | **40,000 QPM**, **30,000,000 QPD** |

Google's examples:
- User A can make up to 1,200 QPM **combined** across her 3 websites (per-user cap).
- Users A and B can make up to 1,200 QPM **combined** to their one website (per-site cap).

**Load limits**: "load" is the internal resources a query consumes.

| Window | Measured in | What to do when exceeded |
|---|---|---|
| Short-term | 10-minute chunks | Wait **15 minutes** and try again. If you only exceed short-term quota, spread your queries throughout the day. |
| Long-term | 1-day chunks | If you exceed quota when running **only a single query inside a 10-minute period**, you are over the long-term quota. Reduce query cost (below). |

What makes a query expensive (from Google):
1. Grouping and/or filtering by **page** or **query** string. **Page AND query together is the most expensive.**
2. **Date range length**: "queries with a six month range are much more expensive than a query with a one day range."
3. **Re-querying the same data** (e.g. pulling all of last month over and over).

**Data ceiling (not a quota, a hard cap):** Search Analytics exposes a maximum of
**50,000 rows of data per day per search type** (web, image, …), sorted by clicks. Paging past
it returns nothing more. For bigger sites use the Search Console bulk data export to BigQuery.

**Per request:** `rowLimit` 1–25,000 (default 1,000); page with `startRow`.

### URL Inspection (`urlInspection.index.inspect`)

| Scope | Limit |
|---|---|
| Per site | **2,000 QPD**, **600 QPM** |
| Per project | **10,000,000 QPD**, **15,000 QPM** |

### All other resources (sites, sitemaps)

| Scope | Limit |
|---|---|
| Per user | **20 QPS**, **200 QPM** |
| Per project | **100,000,000 QPD** |

### Batch requests

A batch of *n* calls counts as **n requests**. A batch holds at most **1,000** calls. Batching
reduces HTTP overhead only. It does not reduce quota usage.

### Where to see usage

Google Cloud console → your project → APIs & Services → Google Search Console API → **Quotas**
(the limits page calls this the "quota tab" of the Google API Console project).

Daily quotas for Google APIs reset at midnight **Pacific Time**. Search Analytics dates are also in PT.

## Budgeting a job

Count requests before running anything:

```
requests ≈ days × search_types × ceil(rows_per_day / 25,000) × filter_variants
```

Worked examples:

| Job | Requests | Fits? |
|---|---|---|
| Daily sync: 1 day × `web` × page+query+country+device (≤ 50k rows → 2 pages) | 2/day | Trivially |
| Daily sync of all 7 `type`s, page+query | ≤ 14/day | Yes |
| Backfill 16 months × `web` × page+query, 1-day queries, 2 pages each | ~970 | Yes, **if spread out** (load quota). Run ≤ ~1 month of days per 10-minute window, back off on `quotaExceeded`. |
| One request: 16-month range grouped by page+query | 1 | **Likely long-term load quota failure**, and it returns only the top 25k rows anyway |
| Inspect 10,000 URLs on one property | 10,000 | **No.** 2,000/day/property → 5 days, or sample |
| 50 properties × daily 1-day sync | ~100/day | Yes. Per-user QPM is shared across properties. |

Rules of thumb:
- **Prefer many cheap queries over one expensive query.** One-day windows are Google's own recommendation.
- **Drop `page`/`query` when you only need totals or trends.** It's cheaper and more accurate.
- **Cache finalized days forever.** Only data newer than ~3 days (or after `metadata.firstIncompleteDate`) can change.
- **Throttle well under the QPM cap** (e.g. ≤ 5 QPS for Search Analytics). The load quota, not QPM, is usually what you hit.
- **One project, many users?** Per-user and per-site caps still apply individually. A shared service account is *one user* for all properties it serves.

## Retry policy that respects the quota model

```
on 429 / 403 rateLimitExceeded / userRateLimitExceeded / 5xx:
    exponential backoff with jitter: sleep(min(64, 2^attempt) + random(0,1)), max ~6 attempts
on quotaExceeded from Search Analytics:
    if not already waited: sleep 15 min, retry once           # short-term load
    else: STOP. Long-term (daily) load quota → make queries cheaper, resume next PT day
on URL Inspection quota errors:
    STOP for the day (2,000/day/property). Persist progress; resume after midnight PT
on 400 / 401 / 403 permission errors:
    never retry blindly; fix the request or credentials
```

`scripts/gsc.py` implements this policy (`--wait-on-quota` enables the single 15-minute wait).
