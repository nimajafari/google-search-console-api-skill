# Batch requests and performance

Sources: https://developers.google.com/webmaster-tools/v1/how-tos/performance and
https://developers.google.com/webmaster-tools/v1/how-tos/batch.

## gzip

You need **both** of these to get a gzip-encoded response:

```
Accept-Encoding: gzip
User-Agent: my program (gzip)
```

Decompression costs some CPU but saves a lot of bandwidth on 25,000-row Search Analytics pages.
`curl --compressed` and the Google client libraries handle decoding. `scripts/gsc.py` sends both headers.

## Partial responses (`fields=`)

Ask for only the fields you need. Works on any request that returns data.

- comma list: `fields=rows,responseAggregationType`
- nesting: `a/b/c`
- sub-selection: `rows(keys,clicks,impressions)`
- wildcard: `items/pagemap/*`
- URL-encode the value. An invalid selection → **400** ("Invalid field selection a/b").

Search Console examples:

```
POST …/searchAnalytics/query?fields=rows(keys,clicks,impressions)
GET  …/sites?fields=siteEntry/siteUrl
GET  …/sites/{siteUrl}/sitemaps?fields=sitemap(path,lastDownloaded,errors,warnings,isPending)
POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect?fields=inspectionResult/indexStatusResult(verdict,coverageState,googleCanonical,userCanonical)
```

Partial responses work best together with pagination (`rowLimit`/`startRow` for Search Analytics).

## HTTP batch

Combines many calls into one HTTP request (`multipart/mixed`), to cut connection overhead.

**Rules**
- At most **1,000 calls** per batch. Use multiple batches beyond that.
- All inner calls must go to the **same API**.
- **Each inner call counts against quota.** *n* calls = *n* requests.
- The server may execute calls **in any order**. If order matters, don't batch them together.
- Send to the API's `batchPath`. For the `searchconsole` discovery doc that is
  `https://searchconsole.googleapis.com/batch` (the generic default is `/batch/api_name/api_version`).
- Each part: `Content-Type: application/http`, optional `Content-ID`, then a full HTTP request
  with **path only**: no scheme/host.
- Outer headers (except `Content-*`) apply to every part. A header on a part overrides the outer one.
- The response is `multipart/mixed` with parts in request order. `Content-ID: <x>` comes back as
  `Content-ID: <response-x>`. Each part has its own status code. Check every one.

```
POST /batch HTTP/1.1
Host: searchconsole.googleapis.com
Authorization: Bearer TOKEN
Content-Type: multipart/mixed; boundary=batch_gsc

--batch_gsc
Content-Type: application/http
Content-ID: <sm1>

GET /webmasters/v3/sites/sc-domain%3Aexample.com/sitemaps

--batch_gsc
Content-Type: application/http
Content-ID: <sm2>

GET /webmasters/v3/sites/sc-domain%3Aexample.org/sitemaps

--batch_gsc--
```

Python client:

```python
def cb(request_id, response, exception):
    if exception: print(request_id, exception)
    else: print(request_id, len(response.get("sitemap", [])))

batch = gsc.new_batch_http_request(callback=cb)
for site in sites:
    batch.add(gsc.sitemaps().list(siteUrl=site), request_id=site)
batch.execute()
```

**When batching helps:** many small calls (sitemaps across 100 properties, a few dozen URL inspections).
**When it doesn't:** Search Analytics paging, where the response is the cost, and anything near a
quota limit, since batching doesn't stretch quota.
