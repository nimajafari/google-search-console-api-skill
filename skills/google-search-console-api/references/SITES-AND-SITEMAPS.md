# Sites and Sitemaps

Sources: https://developers.google.com/webmaster-tools/v1/sites,
https://developers.google.com/webmaster-tools/v1/sitemaps, and the method pages under them.

Base: `https://searchconsole.googleapis.com/webmasters/v3` (also `https://www.googleapis.com/webmasters/v3`).
`{siteUrl}` and `{feedpath}` are path parameters and must be **URL-encoded**.

Quota (both resources): **20 QPS / 200 QPM per user**, 100,000,000 QPD per project.

## Sites

| Method | HTTP | Scope | Body / response |
|---|---|---|---|
| `list` | `GET /sites` | readonly | → `{ "siteEntry": [ {siteUrl, permissionLevel} ] }` |
| `get` | `GET /sites/{siteUrl}` | readonly | → `{siteUrl, permissionLevel}` |
| `add` | `PUT /sites/{siteUrl}` | **webmasters** | no body → empty |
| `delete` | `DELETE /sites/{siteUrl}` | **webmasters** | no body → empty |

`permissionLevel`: `siteOwner`, `siteFullUser`, `siteRestrictedUser`, `siteUnverifiedUser`
([permissions help](https://support.google.com/webmasters/answer/2451999)).

Notes:
- `siteUrl` examples: `http://www.example.com/` (URL-prefix) or `sc-domain:example.com` (Domain).
- `sites.add` adds the property to the user's account, but **doesn't verify it**. Until it is
  verified through another channel (DNS, HTML file, etc.), the permission is `siteUnverifiedUser`
  and data calls fail.
- `sites.delete` removes the property from **this user's** list. It's a destructive, user-visible
  change. Always confirm first.
- `siteEntry` is **absent** when the user has no properties.

## Sitemaps

| Method | HTTP | Scope | Notes |
|---|---|---|---|
| `list` | `GET /sites/{siteUrl}/sitemaps[?sitemapIndex=…]` | readonly | → `{ "sitemap": [ … ] }`. With `sitemapIndex`, lists the sitemaps in that index. |
| `get` | `GET /sites/{siteUrl}/sitemaps/{feedpath}` | readonly | → one sitemap resource |
| `submit` | `PUT /sites/{siteUrl}/sitemaps/{feedpath}` | **webmasters** | no body → empty |
| `delete` | `DELETE /sites/{siteUrl}/sitemaps/{feedpath}` | **webmasters** | no body → empty |

`feedpath` = the full sitemap URL, e.g. `https://www.example.com/sitemap.xml` (encoded in the path).

### Sitemap resource

```json
{
  "path": "https://www.example.com/sitemap.xml",
  "lastSubmitted": "2026-11-01T10:00:00.000Z",
  "isPending": false,
  "isSitemapsIndex": true,
  "type": "sitemap",
  "lastDownloaded": "2026-11-17T08:12:45.000Z",
  "warnings": "0",
  "errors": "0",
  "contents": [{ "type": "web", "submitted": "48210", "indexed": "0" }]
}
```

| Field | Meaning |
|---|---|
| `path` | sitemap URL |
| `lastSubmitted` / `lastDownloaded` | RFC 3339 datetimes |
| `isPending` | true → not processed yet |
| `isSitemapsIndex` | true → it's a sitemap index |
| `type` | `sitemap`, `rssFeed`, `atomFeed`, `urlList`, `patternSitemap`, `notSitemap` |
| `errors` | issues with the sitemap itself that block processing |
| `warnings` | generally non-critical issues with URLs in it |
| `contents[].type` | `web`, `image`, `video`, `news`, `mobile`, `androidApp`, `iosApp`, `pattern` |
| `contents[].submitted` | number of URLs of that type |
| `contents[].indexed` | **Deprecated, don't use.** It's not an index count. Use URL Inspection samples or the Page indexing report in the UI. |

`long` fields (`errors`, `warnings`, `submitted`) are serialized as **strings** in JSON. Cast before comparing.

### Useful checks

- `lastDownloaded` much older than `lastSubmitted`, or `isPending: true` for days: Google isn't fetching it. Check that the URL returns 200, robots.txt allows it, and it isn't too large (50 MB / 50,000 URLs uncompressed per sitemap file).
- `errors > 0`: the sitemap is broken; fix it before anything else.
- `type: notSitemap`: the URL doesn't parse as a sitemap (HTML error page, wrong content).
- Sum `contents[].submitted` across child sitemaps (list with `sitemapIndex=`) to compare against your expected URL inventory.

### Submitting (write)

```bash
python3 scripts/gsc.py sitemap-submit sc-domain:example.com https://www.example.com/sitemap.xml --yes
```

Re-submitting an unchanged sitemap is harmless but unnecessary. Google refetches known sitemaps
on its own. Submit after adding a new sitemap/index or when you want to prompt a refetch.
