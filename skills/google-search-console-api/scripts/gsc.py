#!/usr/bin/env python3
"""gsc.py: quota-aware Google Search Console API helper (Python 3.9+, standard library only).

Commands:
  sites                         list properties and permission levels
  freshness SITE                last final / fresh day of Search Analytics data
  query SITE --start --end ...  Search Analytics with auto-paging, one-day splitting, throttling
  inspect SITE [URL ...]        URL Inspection with a per-property daily budget ledger
  sitemaps SITE                 list sitemaps (optionally the children of a sitemap index)
  sitemap-submit SITE FEED      submit a sitemap (write; needs --yes)
  sitemap-delete SITE FEED      delete a sitemap (write; needs --yes)

Data goes to stdout (or --out), progress and warnings to stderr.

Credentials, first match wins:
  1. --token or $GSC_ACCESS_TOKEN (an OAuth 2.0 access token)
  2. google-auth Application Default Credentials, if `google-auth` + `requests` are installed
     (honours $GOOGLE_APPLICATION_CREDENTIALS for service-account key files)
  3. `gcloud auth application-default print-access-token`

Exit codes: 0 ok, 1 API/other error, 2 usage error, 3 quota exhausted.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

__version__ = "0.1.0"

API_ROOT = os.environ.get("GSC_API_ROOT", "https://searchconsole.googleapis.com").rstrip("/")
SCOPE_RO = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_RW = "https://www.googleapis.com/auth/webmasters"
USER_AGENT = f"gsc-skill/{__version__} (gzip)"  # Google requires "gzip" in the UA for gzip responses

MAX_PAGE = 25_000                 # rowLimit maximum
DAY_ROW_CEILING = 50_000          # rows exposed per day per search type
INSPECT_DAILY_LIMIT = 2_000       # URL Inspection QPD per site
QUOTA_WAIT_SECONDS = 15 * 60      # Google: "wait 15 minutes and try again"

DIMENSIONS = {"date", "hour", "query", "page", "country", "device", "searchAppearance",
              "brandedClassification"}
FILTER_DIMENSIONS = {"query", "page", "country", "device", "searchAppearance", "brandedClassification"}
FILTER_LIST_DIMENSIONS = {"country", "device"}
OPERATORS = {"equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"}
TYPES = {"web", "image", "video", "news", "googleNews", "discover", "webMultimodal"}
AGGREGATIONS = {"auto", "byPage", "byProperty", "byNewsShowcasePanel"}
DATA_STATES = {"final", "all", "hourly_all"}
METRICS = ["clicks", "impressions", "ctr", "position"]

EXIT_OK, EXIT_ERR, EXIT_USAGE, EXIT_QUOTA = 0, 1, 2, 3


def log(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


def die(msg: str, code: int = EXIT_USAGE) -> None:
    log(f"error: {msg}")
    sys.exit(code)


# --------------------------------------------------------------------------- time (Pacific)

def _pacific():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:  # no tz database (e.g. some Windows installs): approximate with PST
        return dt.timezone(dt.timedelta(hours=-8), "PST")


PT = _pacific()


def today_pt() -> dt.date:
    return dt.datetime.now(PT).date()


def parse_day(value: str) -> dt.date:
    """YYYY-MM-DD, 'today', 'yesterday', 'today-N' or 'Nd' (N days ago), in Pacific Time."""
    v = value.strip().lower()
    if v == "today":
        return today_pt()
    if v == "yesterday":
        return today_pt() - dt.timedelta(days=1)
    m = re.fullmatch(r"(?:today-|-)?(\d+)d?", v) if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None
    if m and (v.startswith(("today-", "-")) or v.endswith("d")):
        return today_pt() - dt.timedelta(days=int(m.group(1)))
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"bad date {value!r}: use YYYY-MM-DD, today, yesterday, today-N or Nd (N days ago)")


def day_range(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


# --------------------------------------------------------------------------- auth

def get_token(explicit: str | None, scope: str) -> str:
    if explicit:
        return explicit
    env = os.environ.get("GSC_ACCESS_TOKEN")
    if env:
        return env.strip()
    try:
        import google.auth  # type: ignore
        import google.auth.transport.requests  # type: ignore
        creds, _ = google.auth.default(scopes=[scope])
        creds.refresh(google.auth.transport.requests.Request())
        if creds.token:
            return creds.token
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - report and fall through to gcloud
        log(f"note: google-auth ADC unavailable ({exc.__class__.__name__}: {exc}); trying gcloud")
    try:
        out = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        if out.stderr.strip():
            log(out.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    die("no credentials. Set GSC_ACCESS_TOKEN, install google-auth (+ requests) with ADC or "
        "GOOGLE_APPLICATION_CREDENTIALS, or run `gcloud auth application-default login "
        f"--client-id-file=client_secret.json --scopes={scope},https://www.googleapis.com/auth/cloud-platform`",
        EXIT_ERR)
    return ""  # unreachable


# --------------------------------------------------------------------------- HTTP client

class ApiError(Exception):
    def __init__(self, status: int, text: str):
        self.status = status
        self.text = text
        self.reason, self.message = _parse_error(text)
        super().__init__(f"HTTP {status} {self.reason}: {self.message}".strip())


class QuotaExhausted(ApiError):
    pass


def _parse_error(text: str):
    try:
        err = json.loads(text).get("error", {})
    except (ValueError, AttributeError):
        return "", text[:300]
    reason = ""
    if isinstance(err.get("errors"), list) and err["errors"]:
        reason = err["errors"][0].get("reason", "")
    for det in err.get("details", []) or []:
        reason = reason or det.get("reason", "")
    return reason or err.get("status", ""), err.get("message", "")


def classify(status: int, text: str) -> str:
    """-> 'quota' | 'rate' | 'transient' | 'fatal'"""
    if "quotaExceeded" in text or "dailyLimitExceeded" in text or "load quota" in text.lower():
        return "quota"
    if any(r in text for r in ("rateLimitExceeded", "userRateLimitExceeded", "concurrentLimitExceeded")):
        return "rate"
    if status == 429:
        return "rate"
    if status in (500, 502, 503, 504):
        return "transient"
    return "fatal"


class Client:
    def __init__(self, token: str, min_interval: float, max_retries: int,
                 wait_on_quota: bool, dry_run: bool):
        self.token = token
        self.min_interval = max(0.0, min_interval)
        self.max_retries = max_retries
        self.wait_on_quota = wait_on_quota
        self.dry_run = dry_run
        self.calls = 0
        self._last = 0.0
        self._quota_waited = False

    def _throttle(self) -> None:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def request(self, method: str, path: str, body: dict | None = None,
                params: dict | None = None) -> dict:
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if self.dry_run:
            log(json.dumps({"method": method, "url": url, "body": body}, indent=2))
            return {}
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        attempt = 0
        while True:
            self._throttle()
            self.calls += 1
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT,
                **({"Content-Type": "application/json"} if body is not None else {}),
            })
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read() or b""
                if (exc.headers.get("Content-Encoding") or "").lower() == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                text = raw.decode("utf-8", "replace")
                kind = classify(exc.code, text)
                if kind == "quota":
                    if self.wait_on_quota and not self._quota_waited:
                        self._quota_waited = True
                        log(f"quota exceeded (HTTP {exc.code}); waiting {QUOTA_WAIT_SECONDS // 60} min "
                            "once for the short-term load window...")
                        time.sleep(QUOTA_WAIT_SECONDS)
                        continue
                    raise QuotaExhausted(exc.code, text) from None
                if kind in ("rate", "transient") and attempt < self.max_retries:
                    delay = min(64.0, 2.0 ** attempt) + random.random()
                    attempt += 1
                    log(f"HTTP {exc.code} ({kind}); retry {attempt}/{self.max_retries} in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise ApiError(exc.code, text) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.max_retries:
                    delay = min(64.0, 2.0 ** attempt) + random.random()
                    attempt += 1
                    log(f"network error ({exc}); retry {attempt}/{self.max_retries} in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise


def enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


# --------------------------------------------------------------------------- output

class Writer:
    def __init__(self, fmt: str, out_path: str | None, fields: list[str] | None = None):
        self.fmt = fmt
        self.fh = open(out_path, "w", newline="", encoding="utf-8") if out_path else sys.stdout
        self.fields = fields
        self._csv = None
        self._buf: list[dict] = []
        self.count = 0

    def write(self, row: dict) -> None:
        self.count += 1
        if self.fmt == "jsonl":
            self.fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        elif self.fmt == "json":
            self._buf.append(row)
        else:
            if self._csv is None:
                self._csv = csv.DictWriter(self.fh, fieldnames=self.fields or list(row.keys()),
                                           extrasaction="ignore")
                self._csv.writeheader()
            self._csv.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                for k, v in row.items()})

    def close(self) -> None:
        if self.fmt == "json":
            json.dump(self._buf, self.fh, ensure_ascii=False, indent=2)
            self.fh.write("\n")
        self.fh.flush()
        if self.fh is not sys.stdout:
            self.fh.close()


# --------------------------------------------------------------------------- commands

def cmd_sites(client: Client, args) -> int:
    resp = client.request("GET", "/webmasters/v3/sites")
    w = Writer(args.format, args.out, ["siteUrl", "permissionLevel"])
    for entry in sorted(resp.get("siteEntry", []), key=lambda e: e.get("siteUrl", "")):
        w.write({"siteUrl": entry.get("siteUrl"), "permissionLevel": entry.get("permissionLevel")})
    w.close()
    if w.count == 0 and not client.dry_run:
        log("no properties visible to these credentials (service account not added as a user?)")
    return EXIT_OK


def _sa_path(site: str) -> str:
    return f"/webmasters/v3/sites/{enc(site)}/searchAnalytics/query"


def cmd_freshness(client: Client, args) -> int:
    end = today_pt()
    start = end - dt.timedelta(days=args.days)
    result: dict = {"siteUrl": args.site, "type": args.type, "checkedAtPT": end.isoformat()}
    for state in ("final", "all"):
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
                "dimensions": ["date"], "type": args.type, "dataState": state}
        resp = client.request("POST", _sa_path(args.site), body)
        days = [r["keys"][0] for r in resp.get("rows", [])]
        result[f"last{'Final' if state == 'final' else 'Fresh'}Date"] = days[-1] if days else None
        if state == "final":
            result["finalDaysInWindow"] = len(days)
        else:
            meta = resp.get("metadata") or {}
            result["firstIncompleteDate"] = (meta.get("firstIncompleteDate")
                                             or meta.get("first_incomplete_date"))
    if result.get("lastFinalDate"):
        lag = (end - dt.date.fromisoformat(result["lastFinalDate"])).days
        result["finalLagDays"] = lag
    print(json.dumps(result, indent=2))
    return EXIT_OK


def _parse_filters(raw_filters: list[str], raw_lists: list[str]) -> list[dict]:
    filters, lists = [], []
    for f in raw_filters or []:
        parts = f.split(":", 2)
        if len(parts) == 2:                       # DIM:EXPR -> equals
            dim, op, expr = parts[0], "equals", parts[1]
        elif len(parts) == 3 and parts[1] in OPERATORS:
            dim, op, expr = parts
        elif len(parts) == 3:                     # expression itself contains ':'
            dim, op, expr = parts[0], "equals", f.split(":", 1)[1]
        else:
            die(f"--filter {f!r}: expected DIM:OP:EXPR or DIM:EXPR")
        if dim not in FILTER_DIMENSIONS:
            die(f"--filter dimension {dim!r} not in {sorted(FILTER_DIMENSIONS)}")
        if dim == "brandedClassification" and op != "equals":
            die("brandedClassification only supports the equals operator")
        filters.append({"dimension": dim, "operator": op, "expression": expr})
    for fl in raw_lists or []:
        dim, _, values = fl.partition(":")
        if dim not in FILTER_LIST_DIMENSIONS or not values:
            die(f"--filter-list {fl!r}: expected country:a,b or device:A,B")
        lists.append({"dimension": dim, "expressions": [v for v in values.split(",") if v]})
    clash = {f["dimension"] for f in filters} & {fl["dimension"] for fl in lists}
    if clash:
        die(f"can't filter {sorted(clash)} in both --filter and --filter-list in one request")
    if any(f["dimension"] == "brandedClassification" for f in filters) and \
            any(f["dimension"] == "query" for f in filters):
        die("brandedClassification can't be combined with a query filter in the same request")
    if not filters and not lists:
        return []
    group: dict = {"groupType": "and"}
    if filters:
        group["filters"] = filters
    if lists:
        group["filterLists"] = lists
    return [group]


def _validate_query(args, dims: list[str]) -> None:
    bad = [d for d in dims if d not in DIMENSIONS]
    if bad:
        die(f"unknown dimension(s) {bad}; choose from {sorted(DIMENSIONS)}")
    if len(set(dims)) != len(dims):
        die("a dimension can't be repeated")
    if "hour" in dims and args.data_state != "hourly_all":
        die("the hour dimension requires --data-state hourly_all")
    if "searchAppearance" in dims and len(dims) > 1:
        die("searchAppearance must be the only dimension; list types first, then filter by one "
            "(--filter searchAppearance:equals:TYPE) with other dimensions")
    if "brandedClassification" in dims and any(f.startswith("query:") for f in args.filter or []):
        die("brandedClassification can't be combined with a query filter")
    types = args.type.split(",")
    bad_t = [t for t in types if t not in TYPES]
    if bad_t:
        die(f"unknown type(s) {bad_t}; choose from {sorted(TYPES)}")
    if args.aggregation == "byProperty" and ("page" in dims or any(
            f.startswith("page:") for f in args.filter or [])):
        die("byProperty aggregation isn't allowed when grouping or filtering by page; use auto")
    if args.aggregation == "byProperty" and set(types) & {"discover", "googleNews"}:
        die("byProperty isn't supported for discover / googleNews")
    if args.start > args.end:
        die("--start must be on or before --end")
    if args.end > today_pt():
        log("warning: --end is in the future (Pacific Time); those days will have no data")


def cmd_query(client: Client, args) -> int:
    dims = [d for d in (args.dimensions or "").split(",") if d]
    _validate_query(args, dims)
    groups = _parse_filters(args.filter, args.filter_list)
    types = args.type.split(",")
    windows = ([(d, d) for d in day_range(args.start, args.end)] if args.daily
               else [(args.start, args.end)])
    add_date = args.daily and "date" not in dims and "hour" not in dims
    add_type = len(types) > 1
    fields = (["type"] if add_type else []) + (["date"] if add_date else []) + dims + METRICS
    if args.daily and not dims and len(windows) > 1:
        log("tip: one-day windows with no dimensions give one total row per day; same as --dimensions date")

    est = len(windows) * len(types)
    log(f"plan: {len(windows)} window(s) x {len(types)} type(s) = {est}+ request(s) "
        f"({'daily' if args.daily else 'single range'}; dims={dims or 'none'})")
    if not args.daily and (args.end - args.start).days > 31 and {"page", "query"} & set(dims):
        log("warning: long range grouped by page/query is the most expensive query shape "
            "(load quota). Consider --daily.")

    w = Writer(args.format, args.out, fields)
    rc = EXIT_OK
    try:
        for t in types:
            for (s, e) in windows:
                got = 0
                start_row = 0
                while True:
                    page = MAX_PAGE if args.row_limit is None else min(MAX_PAGE, args.row_limit - got)
                    if page <= 0:
                        break
                    body: dict = {"startDate": s.isoformat(), "endDate": e.isoformat(),
                                  "dimensions": dims, "type": t, "rowLimit": page,
                                  "startRow": start_row}
                    if groups:
                        body["dimensionFilterGroups"] = groups
                    if args.aggregation:
                        body["aggregationType"] = args.aggregation
                    if args.data_state:
                        body["dataState"] = args.data_state
                    resp = client.request("POST", _sa_path(args.site), body,
                                          {"fields": args.fields} if args.fields else None)
                    rows = resp.get("rows", [])
                    meta = resp.get("metadata") or {}
                    for k in ("firstIncompleteDate", "first_incomplete_date",
                              "firstIncompleteHour", "first_incomplete_hour"):
                        if meta.get(k):
                            log(f"note: {k}={meta[k]} (values from here on may still change)")
                    for r in rows:
                        out: dict = {}
                        if add_type:
                            out["type"] = t
                        if add_date:
                            out["date"] = s.isoformat()
                        out.update(zip(dims, r.get("keys", [])))
                        for m in METRICS:
                            out[m] = r.get(m)
                        w.write(out)
                    got += len(rows)
                    start_row += len(rows)
                    if len(rows) < page or client.dry_run:
                        break
                label = s.isoformat() if s == e else f"{s}..{e}"
                log(f"{t} {label}: {got} rows")
                if args.daily and got >= DAY_ROW_CEILING:
                    log(f"warning: {label} reached the {DAY_ROW_CEILING:,} rows/day/type ceiling; "
                        "the API doesn't expose more. Use BigQuery bulk export for complete data.")
    except QuotaExhausted as exc:
        log(f"STOPPED: {exc}\n  Search Analytics load quota. If one query alone keeps failing you are over the "
            "daily (long-term) load quota: shorten the date range (use --daily), drop page/query "
            "dimensions, and resume tomorrow (Pacific Time). Rows written so far are valid.")
        rc = EXIT_QUOTA
    finally:
        w.close()
        log(f"done: {w.count} rows, {client.calls} API call(s)")
    return rc


# ---- URL inspection ---------------------------------------------------------

def _ledger_path(arg: str | None) -> str:
    if arg:
        return arg
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "gsc-skill", "inspect-ledger.json")


def _load_ledger(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_ledger(path: str, ledger: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cutoff = (today_pt() - dt.timedelta(days=7)).isoformat()   # keep a week of history
    pruned = {site: {d: n for d, n in days.items() if d >= cutoff} for site, days in ledger.items()}
    pruned = {s: d for s, d in pruned.items() if d}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(pruned, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _summarize(url: str, res: dict) -> dict:
    idx = res.get("indexStatusResult", {}) or {}
    g, u = idx.get("googleCanonical"), idx.get("userCanonical")
    rich = res.get("richResultsResult") or {}
    return {
        "url": url,
        "verdict": idx.get("verdict"),
        "coverageState": idx.get("coverageState"),
        "indexingState": idx.get("indexingState"),
        "robotsTxtState": idx.get("robotsTxtState"),
        "pageFetchState": idx.get("pageFetchState"),
        "lastCrawlTime": idx.get("lastCrawlTime"),
        "crawledAs": idx.get("crawledAs"),
        "googleCanonical": g,
        "userCanonical": u,
        "canonicalMismatch": bool(g and u and g != u),
        "inSitemaps": len(idx.get("sitemap", []) or []),
        "richResultsVerdict": rich.get("verdict"),
        "richResultTypes": [d.get("richResultType") for d in rich.get("detectedItems", []) or []],
        "inspectionResultLink": res.get("inspectionResultLink"),
    }


INSPECT_FIELDS = list(_summarize("", {}).keys()) + ["error"]


def cmd_inspect(client: Client, args) -> int:
    urls: list[str] = list(args.urls or [])
    if args.file:
        fh = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
        with fh:
            urls += [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    if not ordered:
        die("no URLs given (positional URLs or --file PATH|-)")

    ledger_file = _ledger_path(args.ledger)
    ledger = _load_ledger(ledger_file)
    today = today_pt().isoformat()
    used = ledger.get(args.site, {}).get(today, 0)
    budget = min(args.budget, INSPECT_DAILY_LIMIT)
    remaining = max(0, budget - used)
    log(f"URL inspection: {len(ordered)} URL(s); used today (PT {today}) for {args.site}: {used}; "
        f"budget left: {remaining}")
    if remaining < len(ordered):
        log(f"warning: only the first {remaining} URL(s) will be inspected today")

    w = Writer(args.format, args.out, None if args.full else INSPECT_FIELDS)
    rc = EXIT_OK
    try:
        for url in ordered[:remaining]:
            body = {"inspectionUrl": url, "siteUrl": args.site, "languageCode": args.language}
            try:
                resp = client.request("POST", "/v1/urlInspection/index:inspect", body)
            except QuotaExhausted as exc:
                log(f"STOPPED: {exc}\n  URL Inspection quota is 2,000/day and 600/min per property; "
                    "resume after midnight Pacific Time.")
                ledger.setdefault(args.site, {})[today] = INSPECT_DAILY_LIMIT
                rc = EXIT_QUOTA
                break
            except ApiError as exc:
                if exc.status == 400:     # bad URL / not under property: record and continue
                    w.write({"url": url, "error": str(exc)})
                    continue
                raise
            if client.dry_run:
                continue
            ledger.setdefault(args.site, {})[today] = ledger.get(args.site, {}).get(today, 0) + 1
            res = resp.get("inspectionResult", {})
            w.write({"url": url, **res} if args.full else _summarize(url, res))
    finally:
        w.close()
        if not client.dry_run:
            _save_ledger(ledger_file, ledger)
        log(f"done: {w.count} result(s), {client.calls} API call(s); ledger: {ledger_file}")
    return rc


# ---- sitemaps ---------------------------------------------------------------

SITEMAP_FIELDS = ["path", "type", "isSitemapsIndex", "isPending", "lastSubmitted", "lastDownloaded",
                  "errors", "warnings", "submittedUrls", "contents"]


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def cmd_sitemaps(client: Client, args) -> int:
    resp = client.request("GET", f"/webmasters/v3/sites/{enc(args.site)}/sitemaps",
                          params={"sitemapIndex": args.index} if args.index else None)
    w = Writer(args.format, args.out, SITEMAP_FIELDS)
    for sm in resp.get("sitemap", []):
        contents = [{"type": c.get("type"), "submitted": _int(c.get("submitted"))}
                    for c in sm.get("contents", []) or []]  # contents[].indexed is deprecated
        w.write({
            "path": sm.get("path"), "type": sm.get("type"),
            "isSitemapsIndex": sm.get("isSitemapsIndex", False), "isPending": sm.get("isPending", False),
            "lastSubmitted": sm.get("lastSubmitted"), "lastDownloaded": sm.get("lastDownloaded"),
            "errors": _int(sm.get("errors")), "warnings": _int(sm.get("warnings")),
            "submittedUrls": sum(c["submitted"] for c in contents), "contents": contents,
        })
    w.close()
    return EXIT_OK


def cmd_sitemap_write(client: Client, args, method: str) -> int:
    verb = "submit" if method == "PUT" else "delete"
    if not args.yes and not client.dry_run:
        die(f"sitemap {verb} changes Search Console state; re-run with --yes to confirm")
    client.request(method, f"/webmasters/v3/sites/{enc(args.site)}/sitemaps/{enc(args.feed)}")
    log(f"sitemap {verb}: {args.feed} on {args.site}: OK" if not client.dry_run else "(dry run)")
    return EXIT_OK


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", help="OAuth access token (else $GSC_ACCESS_TOKEN, google-auth ADC, gcloud)")
    common.add_argument("--format", choices=["jsonl", "csv", "json"], default="jsonl",
                        help="output format (default jsonl)")
    common.add_argument("--out", help="write data to this file instead of stdout")
    common.add_argument("--qps", type=float, default=None,
                        help="max requests per second (default: 5 for query, 1 for inspect, 2 otherwise)")
    common.add_argument("--max-retries", type=int, default=6, help="retries on 429/5xx (default 6)")
    common.add_argument("--wait-on-quota", action="store_true",
                        help="on quotaExceeded, wait 15 min once before giving up (short-term load quota)")
    common.add_argument("--dry-run", action="store_true", help="print requests to stderr; send nothing")

    p = argparse.ArgumentParser(prog="gsc.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites", parents=[common], help="list properties and permission levels")

    f = sub.add_parser("freshness", parents=[common], help="find the last final / fresh data day")
    f.add_argument("site")
    f.add_argument("--days", type=int, default=10, help="look-back window (default 10)")
    f.add_argument("--type", default="web", choices=sorted(TYPES))

    q = sub.add_parser("query", parents=[common], help="Search Analytics query with paging",
                       description="Dates accept YYYY-MM-DD, today, yesterday or -Nd (Pacific Time).")
    q.add_argument("site", help="sc-domain:example.com or https://www.example.com/")
    q.add_argument("--start", type=parse_day, required=True)
    q.add_argument("--end", type=parse_day, required=True)
    q.add_argument("--dimensions", default="", help="comma list: " + ",".join(sorted(DIMENSIONS)))
    q.add_argument("--type", default="web", help="comma list of: " + ",".join(sorted(TYPES)))
    q.add_argument("--filter", action="append",
                   help="DIM:OP:EXPR or DIM:EXPR (equals). OP: " + ", ".join(sorted(OPERATORS)))
    q.add_argument("--filter-list", action="append", help="country:usa,can or device:MOBILE,TABLET")
    q.add_argument("--aggregation", choices=sorted(AGGREGATIONS))
    q.add_argument("--data-state", choices=sorted(DATA_STATES))
    q.add_argument("--row-limit", type=int, default=None,
                   help="max rows per window (default: all pages, up to the API's ceiling)")
    q.add_argument("--daily", action="store_true",
                   help="split the range into one-day queries (Google's recommended, quota-friendly pattern)")
    q.add_argument("--fields", help="partial response selector, e.g. 'rows(keys,clicks)'")

    i = sub.add_parser("inspect", parents=[common], help="URL Inspection with a daily budget ledger")
    i.add_argument("site")
    i.add_argument("urls", nargs="*")
    i.add_argument("--file", help="file with one URL per line ('-' for stdin; # comments ok)")
    i.add_argument("--language", default="en-US", help="BCP-47 code for issue messages")
    i.add_argument("--full", action="store_true", help="emit the raw inspectionResult")
    i.add_argument("--budget", type=int, default=INSPECT_DAILY_LIMIT,
                   help="max inspections per property per PT day, counted in the ledger (≤ 2000)")
    i.add_argument("--ledger", help="ledger path (default ~/.cache/gsc-skill/inspect-ledger.json)")

    s = sub.add_parser("sitemaps", parents=[common], help="list sitemaps")
    s.add_argument("site")
    s.add_argument("--index", help="list the children of this sitemap index URL")

    for name in ("sitemap-submit", "sitemap-delete"):
        sp = sub.add_parser(name, parents=[common], help=f"{name.split('-')[1]} a sitemap (write)")
        sp.add_argument("site")
        sp.add_argument("feed", help="full sitemap URL")
        sp.add_argument("--yes", action="store_true", help="confirm the write")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    write = args.cmd in ("sitemap-submit", "sitemap-delete")
    default_qps = {"query": 5.0, "freshness": 5.0, "inspect": 1.0}.get(args.cmd, 2.0)
    qps = args.qps if args.qps and args.qps > 0 else default_qps
    if args.cmd == "inspect" and qps > 10:
        die("URL Inspection is limited to 600/min per property; use --qps 10 or less")
    token = "DRY-RUN" if args.dry_run else get_token(args.token, SCOPE_RW if write else SCOPE_RO)
    client = Client(token, 1.0 / qps, args.max_retries, args.wait_on_quota, args.dry_run)
    try:
        if args.cmd == "sites":
            return cmd_sites(client, args)
        if args.cmd == "freshness":
            return cmd_freshness(client, args)
        if args.cmd == "query":
            return cmd_query(client, args)
        if args.cmd == "inspect":
            return cmd_inspect(client, args)
        if args.cmd == "sitemaps":
            return cmd_sitemaps(client, args)
        if args.cmd == "sitemap-submit":
            return cmd_sitemap_write(client, args, "PUT")
        if args.cmd == "sitemap-delete":
            return cmd_sitemap_write(client, args, "DELETE")
    except QuotaExhausted as exc:
        log(f"error: {exc}")
        return EXIT_QUOTA
    except ApiError as exc:
        log(f"error: {exc}")
        if exc.status == 403:
            log("hint: run `gsc.py sites` with the same credentials and use siteUrl exactly as listed; "
                "service accounts must be added as users on the property in Search Console; "
                "writes need the webmasters (read/write) scope.")
        elif exc.status == 401:
            log("hint: token missing/expired or lacks a Search Console scope.")
        return EXIT_ERR
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
