# Google Search Console API Skill

An [Agent Skill](https://agentskills.io/) that teaches your coding agent to use the
[Google Search Console API](https://developers.google.com/webmaster-tools/about) properly:
Search Analytics, URL Inspection, Sitemaps and Sites, **without blowing the quota or silently
losing rows**.

Making one call to the API is easy. Getting complete, correct data at scale is the hard part:
load quotas that punish long date ranges and page+query grouping, a 25,000-row page size, a
50,000-rows-per-day ceiling, data dropped for privacy and computation, `byPage` vs `byProperty`
totals, Pacific-time dates, and 2,000 URL inspections per property per day. This skill puts all of
that in front of the agent, plus a tested CLI that does it correctly.

## What it covers

- **Quotas**: every Search Analytics, URL Inspection and other-resource limit, the load-quota cost model, a budgeting worksheet and a retry policy ([LIMITS.md](skills/google-search-console-api/references/LIMITS.md))
- **Search Analytics**: full request/response schema, all dimensions, `type`s, filter operators, `filterLists`, aggregation, `dataState` / hourly data, branded-query classification, the two-step search appearance pattern, and why numbers don't match the UI ([SEARCH-ANALYTICS.md](skills/google-search-console-api/references/SEARCH-ANALYTICS.md))
- **URL Inspection**: every result field and enum, a triage table, and bulk-inspection strategy under 2,000/day ([URL-INSPECTION.md](skills/google-search-console-api/references/URL-INSPECTION.md))
- **Sites and Sitemaps**: permissions, `siteUrl` formats, sitemap health checks ([SITES-AND-SITEMAPS.md](skills/google-search-console-api/references/SITES-AND-SITEMAPS.md))
- **Auth and setup**: OAuth scopes, service accounts (and the "add it as a user in Search Console" step), desktop OAuth, gcloud ADC, client libraries for 10 languages ([AUTH-AND-SETUP.md](skills/google-search-console-api/references/AUTH-AND-SETUP.md))
- **Errors**: a decision table for what to retry and what to fix ([ERRORS.md](skills/google-search-console-api/references/ERRORS.md))
- **Batch and performance**: gzip, `fields=` partial responses, multipart batch ([BATCH-AND-PERFORMANCE.md](skills/google-search-console-api/references/BATCH-AND-PERFORMANCE.md))
- **`scripts/gsc.py`**: a single-file, standard-library-only Python CLI (3.9+)

### The CLI

```bash
S=skills/google-search-console-api/scripts/gsc.py
python3 $S sites                                         # properties + permission level
python3 $S freshness sc-domain:example.com               # last final day, first incomplete day
python3 $S query sc-domain:example.com --start 30d --end 3d \
    --dimensions page,query --daily --format csv > gsc.csv
python3 $S inspect sc-domain:example.com --file urls.txt  # summary JSONL, 2,000/day ledger
python3 $S sitemaps sc-domain:example.com
python3 $S query ... --dry-run                           # show the request, send nothing
```

It pages through results at 25,000 rows, splits ranges into one-day queries (`--daily`),
throttles, backs off on rate limits, **stops cleanly on load-quota errors** (exit code 3, with
the fix to apply), keeps a per-property daily ledger for URL Inspection, validates requests the
API would reject before spending quota, and requires `--yes` for writes.

Credentials: `GSC_ACCESS_TOKEN`, or `google-auth` Application Default Credentials (service-account
key via `GOOGLE_APPLICATION_CREDENTIALS`), or `gcloud auth application-default print-access-token`.

## Install

**Claude Code (plugin):**

```text
/plugin marketplace add nimajafari/google-search-console-api-skill
/plugin install google-search-console-api-skill@nimajafari-google-search-console-api-skill
```

**Any agent, via the [`skills`](https://github.com/vercel-labs/skills) CLI:**

```bash
npx skills add nimajafari/google-search-console-api-skill
```

**Manual:**

```bash
git clone https://github.com/nimajafari/google-search-console-api-skill.git
cp -r google-search-console-api-skill/skills/google-search-console-api ~/.claude/skills/
```

**Gemini CLI:** `gemini extensions install https://github.com/nimajafari/google-search-console-api-skill`

**Codex CLI:** `codex plugin marketplace add nimajafari/google-search-console-api-skill`

**Antigravity:** `agy plugin install https://github.com/nimajafari/google-search-console-api-skill`

**Cursor:** add the repo as a plugin (`.cursor-plugin/plugin.json`).

**Other agents:** copy `skills/google-search-console-api/` into the agent's skills directory
(`.agents/skills/`, `~/.copilot/skills/`, `.windsurf/skills/`, `.roo/skills/`, `.kiro/skills/`, …).

## Usage

The skill activates when your request matches its description. For example:

```
Pull the last 16 months of page+query data for sc-domain:example.com into a CSV without hitting quota
```

```
Why does my Search Console API total not match the Performance report?
```

```
Inspect our top 500 pages by clicks and list every one where Google chose a different canonical
```

```
Our nightly GSC sync started failing with quotaExceeded. Fix it.
```

## Requirements

- A Google Cloud project with the **Google Search Console API** enabled
- OAuth 2.0 credentials (service account added as a user on the property, or a desktop OAuth client)
- Python 3.9+ for `scripts/gsc.py` (no packages required; `google-auth` optional)

## Sources

Built from Google's official documentation: [About](https://developers.google.com/webmaster-tools/about),
[Usage limits](https://developers.google.com/webmaster-tools/limits),
[Prerequisites](https://developers.google.com/webmaster-tools/v1/prereqs),
[Client libraries](https://developers.google.com/webmaster-tools/v1/libraries),
[Authorizing](https://developers.google.com/webmaster-tools/v1/how-tos/authorizing),
[Performance tips](https://developers.google.com/webmaster-tools/v1/how-tos/performance),
[Batch](https://developers.google.com/webmaster-tools/v1/how-tos/batch),
[Search Analytics](https://developers.google.com/webmaster-tools/v1/how-tos/search_analytics),
[All your data](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data), the
[API reference](https://developers.google.com/webmaster-tools/v1/api_reference_index) and the
`searchconsole` v1 discovery document.

## Related

- [nimajafari/lighthouse-skill](https://github.com/nimajafari/lighthouse-skill): lab measurement with Lighthouse.

## License

MIT. See [LICENSE](LICENSE). Not affiliated with or endorsed by Google. "Google Search Console"
is a trademark of Google LLC.
