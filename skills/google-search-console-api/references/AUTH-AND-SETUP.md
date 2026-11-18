# Authentication, setup and client libraries

Sources: https://developers.google.com/webmaster-tools/v1/prereqs,
https://developers.google.com/webmaster-tools/v1/how-tos/authorizing,
https://developers.google.com/webmaster-tools/v1/libraries.

## Prerequisites

1. **A Google Account with Search Console permission on the property.** Each method needs the
   matching permission. E.g. `searchanalytics.query` needs read permission. Owner, full or
   restricted (read) users can read. Writes (sitemap submit/delete, site add/delete) need the
   `webmasters` scope and an owner/full user.
2. **Familiarity with the Search Console UI.** Each API mirrors a report. Read the report's help
   page before interpreting API data.
3. **A Google Cloud project** with the **Google Search Console API** enabled
   (console.cloud.google.com → APIs & Services → Library).
4. **OAuth 2.0 credentials.** All Search Console APIs (except the old Testing Tools API) require
   OAuth 2.0. **No other authorization protocol is supported.** A plain API key can't read
   property data.

## Scopes

| Scope | Access |
|---|---|
| `https://www.googleapis.com/auth/webmasters.readonly` | Read-only |
| `https://www.googleapis.com/auth/webmasters` | Read/write |

Default to `webmasters.readonly`. Only request `webmasters` for sitemap submit/delete or site add/delete.

## The OAuth flow (all app types)

1. Register the app in the Google Cloud console → get a client ID (and secret).
2. Enable the Search Console API.
3. The app requests a scope → Google shows a consent screen → the user approves.
4. Google returns a short-lived access token (plus a refresh token for offline access).
5. Send `Authorization: Bearer <token>` on every request. Refresh when it expires.

## Choosing a credential

### A. Service account (unattended jobs, pipelines, CI)

1. Cloud console → IAM & Admin → Service accounts → create one. Prefer **keyless** options
   (attached service account on Cloud Run/GCE/GKE, or impersonation) over downloading a JSON key.
2. **In Search Console**, open the property → Settings → Users and permissions → **Add user** →
   the service account's email (`name@project.iam.gserviceaccount.com`). Choose Restricted for
   read-only work and Full/Owner for writes. **Skipping this step is the most common cause of
   403 "User does not have sufficient permission for site".**
3. Use `sc-domain:` / URL-prefix `siteUrl` exactly as `sites.list` returns it *for that service account*.

```python
# key file (GOOGLE_APPLICATION_CREDENTIALS) or attached SA: same code
import google.auth
from googleapiclient.discovery import build
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
gsc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
print(gsc.sites().list().execute().get("siteEntry", []))
```

Keyless impersonation from a developer machine:

```python
from google.auth import default, impersonated_credentials
source, _ = default()
creds = impersonated_credentials.Credentials(
    source_credentials=source,
    target_principal="gsc-reader@my-project.iam.gserviceaccount.com",
    target_scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
```

(The caller needs `roles/iam.serviceAccountTokenCreator` on the service account.)

### B. Installed / desktop OAuth client (a human running scripts)

Cloud console → APIs & Services → Credentials → Create credentials → OAuth client ID →
**Desktop app** → download `client_secret.json`. Configure the OAuth consent screen. While the
app is in "Testing" status, add your account as a test user, and expect refresh tokens to expire
after about 7 days.

```python
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/webmasters.readonly"])
creds = flow.run_local_server(port=0)        # opens a browser for consent
open("token.json", "w").write(creds.to_json())  # gitignore this file
```

Or create Application Default Credentials with gcloud using **your own** client ID:

```bash
gcloud auth application-default login \
  --client-id-file=client_secret.json \
  --scopes=https://www.googleapis.com/auth/webmasters.readonly,https://www.googleapis.com/auth/cloud-platform
gcloud auth application-default print-access-token   # what scripts/gsc.py falls back to
```

If you get *"Search Console API has not been used in project 764086051850…"* or an "app blocked"
consent screen, you're on gcloud's built-in client. Use `--client-id-file` with your own client.

### C. Web server apps

Use the standard server-side OAuth 2.0 web flow with `access_type=offline` so you get a refresh
token. Store refresh tokens encrypted, per user. Each end user only sees properties *they* have
access to.

### API keys (only for the old Testing Tools API)

The Search Console **Testing Tools API** (Mobile-Friendly Test) accepted an API key
(`?key=yourAPIKey`), restricted in the Credentials page. Google retired the Mobile-Friendly Test
tool and API in December 2023. Don't build on it, even though `urlTestingTools.mobileFriendlyTest.run`
still appears in the discovery document. Use Lighthouse / PageSpeed Insights instead.

## Client libraries

The API is plain HTTP + JSON, so any HTTP client works. Google's libraries add auth helpers,
discovery, batching and retries.

| Language | Package / install | Entry point |
|---|---|---|
| Python | `pip install --upgrade google-api-python-client google-auth google-auth-oauthlib` (v2 needs Python 3.7+) | `build("searchconsole", "v1", credentials=creds)`; legacy `build("webmasters", "v3")` still works for the v3 resources |
| Node.js | `npm i googleapis` (or the per-API `@googleapis/searchconsole`) | `google.searchconsole({version: "v1", auth})` |
| Java | Maven `com.google.apis:google-api-services-searchconsole` | `SearchConsole` service class |
| Go | `go get google.golang.org/api/searchconsole/v1` | `searchconsole.NewService(ctx, option.WithScopes(...))` |
| .NET | NuGet `Google.Apis` (per-API package `Google.Apis.SearchConsole.v1`) | `SearchConsoleService` |
| PHP | `composer require google/apiclient` | `new Google\Service\SearchConsole($client)` |
| Ruby | `gem install google-api-client` (or the per-API `google-apis-searchconsole_v1`) | `Google::Apis::SearchconsoleV1::SearchConsoleService` |
| Dart | `googleapis` on pub.dev | `SearchConsoleApi` |
| JavaScript (browser) | Google API Client Library for JavaScript (`gapi`) | `gapi.client.searchconsole` |
| Objective-C | google-api-objectivec-client-for-rest | `GTLRSearchConsoleService` |

Python sample from Google: https://github.com/google/google-api-python-client/tree/master/samples/searchconsole

## Raw HTTP

```bash
TOKEN=$(gcloud auth application-default print-access-token)
SITE=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "sc-domain:example.com")
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept-Encoding: gzip" -A "my-gsc-sync (gzip)" --compressed \
  "https://searchconsole.googleapis.com/webmasters/v3/sites/$SITE/searchAnalytics/query" \
  -d '{"startDate":"2026-11-14","endDate":"2026-11-14","dimensions":["page"],"rowLimit":10}'
```

## Secrets hygiene

- Never commit `client_secret.json`, `token.json` or service-account keys. Add them to `.gitignore`.
- Never echo tokens into logs, CI output or chat transcripts.
- Use read-only scope and the Restricted permission level wherever possible.
- Rotate or delete unused service-account keys. Prefer keyless auth.
