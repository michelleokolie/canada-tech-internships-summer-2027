#!/usr/bin/env python3
"""Find Canadian / remote tech internships on Ashby, Greenhouse and Lever and add
them to .github/scripts/listings.json (the file the README tables are built from).

Flow:
  1. Discovery: run the boolean searches in .github/bot-data/queries.txt through the
     Brave Search API and collect company boards from the result URLs.
  2. Fetch: read each board's public JSON API (Ashby, Greenhouse, Lever).
  3. Rule filter: intern/co-op titles with a Canadian or remote location.
  4. LLM filter: a local Ollama model checks tech role, Canada/remote, and the season.
  5. Append new entries to listings.json and write pr_body.md for review.
     update_readmes.py then rebuilds README.md and OFFSEASON_README.md.

Usage:
  python .github/scripts/find_internships.py            # normal run
  python .github/scripts/find_internships.py --dry-run  # print changes, write nothing
  python .github/scripts/find_internships.py --no-llm   # keyword rules only
"""
import html
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests

ROOT = Path(os.environ.get("BOT_ROOT") or Path(__file__).resolve().parents[2])
LISTINGS = ROOT / ".github" / "scripts" / "listings.json"
DATA = ROOT / ".github" / "bot-data"
COMPANIES = DATA / "companies.txt"
QUERIES = DATA / "queries.txt"
NAMES = DATA / "company_names.json"
SEEN = DATA / "seen.json"
PR_BODY = ROOT / "pr_body.md"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")
SEARCH_PAGES = int(os.environ.get("SEARCH_PAGES", "3"))
TARGET_YEAR = 2027

INTERN_RE = re.compile(r"\b(intern|interns|internship|co-?op)\b", re.I)
CANADA_HINTS = [
    "canada", "toronto", "vancouver", "montreal", "montréal", "ottawa",
    "waterloo", "calgary", "edmonton", "winnipeg", "kitchener", "mississauga",
    "quebec", "québec", "ontario", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "halifax", "saskatoon", "regina",
]
PROVINCE_RE = re.compile(r",\s*(ON|BC|AB|MB|QC|NS|NB|SK|NL|PE)\b")

SOURCE_PATTERNS = [
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)")),
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.[a-z]+)?\.greenhouse\.io/([^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/?#]+)")),
]
IGNORED_SLUGS = {"embed", "v1", "api", "careers", "jobs"}


# ---------- small helpers ----------

def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def normalize_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", "", ""))


def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(text or ""))).strip()


def to_ts(value):
    """ISO string or epoch (s or ms) to epoch seconds."""
    if value is None:
        return int(time.time())
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1e11 else int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return int(time.time())


# ---------- 1. discovery ----------

def discover_boards(queries):
    if not BRAVE_KEY:
        print("No BRAVE_API_KEY set, skipping discovery. Using companies file only.")
        return set()
    found = set()
    for q in queries:
        for page in range(SEARCH_PAGES):
            try:
                r = requests.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": q, "count": 20, "offset": page},
                    headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"},
                    timeout=30,
                )
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"search failed ({q!r}, page {page}): {e}")
                break
            results = r.json().get("web", {}).get("results", [])
            if not results:
                break
            for item in results:
                for src, pat in SOURCE_PATTERNS:
                    m = pat.search(item.get("url", ""))
                    if m and m.group(1).lower() not in IGNORED_SLUGS:
                        found.add(f"{src}:{m.group(1).lower()}")
            time.sleep(1.1)  # free tier allows about 1 request per second
    print(f"Discovery found {len(found)} boards.")
    return found


# ---------- 2. fetchers (each returns a list of normalized jobs) ----------

def get_json(url):
    try:
        r = requests.get(url, timeout=30)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def split_locations(text):
    return [p.strip() for p in re.split(r";|\s\|\s", text or "") if p.strip()]


def fetch_ashby(slug):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}") or {}
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j["location"]] if j.get("location") else []
        for s in j.get("secondaryLocations") or []:
            name = s.get("location") if isinstance(s, dict) else s
            if name:
                locs.append(name)
        country = (((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or "")
        out.append({
            "title": j.get("title", ""), "url": j.get("jobUrl") or j.get("applyUrl"),
            "locations": locs, "remote": bool(j.get("isRemote")), "country": country,
            "posted": to_ts(j.get("publishedAt")), "desc": j.get("descriptionPlain") or "",
        })
    return out


def fetch_greenhouse(slug):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true") or {}
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append({
            "title": j.get("title", ""), "url": j.get("absolute_url"),
            "locations": split_locations(loc), "remote": "remote" in loc.lower(), "country": "",
            "posted": to_ts(j.get("first_published") or j.get("updated_at")),
            "desc": strip_html(j.get("content")),
        })
    return out


def fetch_lever(slug):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        out.append({
            "title": j.get("text", ""), "url": j.get("hostedUrl") or j.get("applyUrl"),
            "locations": locs, "remote": (j.get("workplaceType") == "remote"),
            "country": j.get("country") or "",
            "posted": to_ts(j.get("createdAt")), "desc": j.get("descriptionPlain") or "",
        })
    return out


FETCHERS = {"ashby": fetch_ashby, "greenhouse": fetch_greenhouse, "lever": fetch_lever}


# ---------- 3. rule filter ----------

def passes_rules(job):
    if not job.get("url") or not INTERN_RE.search(job["title"]):
        return False
    blob = " | ".join(job["locations"]).lower()
    if job["country"].lower() in ("canada", "ca") or any(h in blob for h in CANADA_HINTS):
        return True
    if PROVINCE_RE.search(" | ".join(job["locations"])):
        return True
    return job["remote"] or "remote" in blob  # the model decides if remote is open to Canada


# ---------- 4. LLM filter ----------

PROMPT = """You are screening job postings for a Canadian student internship list.
Today is {today}. The list covers internships starting in 2027.

Posting:
Company: {company}
Title: {title}
Locations: {locations}
Remote flag: {remote}
Description (truncated): {desc}

Answer with JSON only, using these keys:
- "tech_role": true if this is a software, data, ML, security, IT, product management, or quant role, else false
- "canada_ok": true if it is based in Canada, or remote and open to people in Canada. false if remote but limited to another country, or based outside Canada
- "season": "summer", "fall", "winter", "spring", or "unclear", based on when the internship term starts
- "year": the four digit year of that term as a number, or null if not stated
- "reason": one short sentence
"""

SEASON_RE = re.compile(r"\b(summer|fall|autumn|winter|spring)\s*(?:term\s*)?'?(20)?(2\d)\b", re.I)


def heuristic_season(text):
    m = SEASON_RE.search(text or "")
    if not m:
        return "unclear", None
    season = m.group(1).lower().replace("autumn", "fall")
    return season, int("20" + m.group(3))


def classify(job, company, use_llm=True):
    hs, hy = heuristic_season(job["title"] + " " + job["desc"][:1500])
    fallback = {"tech_role": True, "canada_ok": True, "season": hs, "year": hy, "reason": "rules only"}
    if not use_llm:
        return fallback
    prompt = PROMPT.format(
        today=datetime.now().strftime("%B %d, %Y"), company=company, title=job["title"],
        locations="; ".join(job["locations"]) or "unspecified", remote=job["remote"],
        desc=job["desc"][:1500],
    )
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "format": "json", "options": {"temperature": 0}},
            timeout=300,
        )
        r.raise_for_status()
        d = json.loads(r.json()["response"])
        year = d.get("year")
        return {
            "tech_role": bool(d.get("tech_role")), "canada_ok": bool(d.get("canada_ok")),
            "season": str(d.get("season", "unclear")).lower(),
            "year": int(year) if str(year).isdigit() else None,
            "reason": str(d.get("reason", ""))[:200],
        }
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        fallback["reason"] = f"model unavailable ({type(e).__name__}), needs manual check"
        return fallback


def decide_season(v):
    """Return the listings.json season ('Summer', 'Fall', ...) or None to skip."""
    if not (v["tech_role"] and v["canada_ok"]):
        return None
    if v["year"] not in (None, TARGET_YEAR):
        return None
    if v["season"] in ("fall", "winter", "spring"):
        return v["season"].capitalize()
    return "Summer"  # summer, or unclear (flagged in the PR)


# ---------- 5. listings.json ----------

def pretty_company(slug):
    return " ".join(w.capitalize() for w in re.split(r"[-_]", slug) if w)


def company_name(src, slug, names):
    key = f"{src}:{slug}"
    if key not in names:
        name = None
        if src == "greenhouse":
            name = (get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}") or {}).get("name")
        names[key] = name or pretty_company(slug)
    return names[key]


def make_listing(company, job, season):
    now = int(time.time())
    return {
        "source": "internship-bot", "company_name": company, "id": str(uuid.uuid4()),
        "title": job["title"], "active": True, "date_updated": now, "is_visible": True,
        "date_posted": job["posted"], "url": normalize_url(job["url"]),
        "locations": job["locations"] or (["Remote"] if job["remote"] else ["Canada"]),
        "season": season, "company_url": "",
    }


def main():
    dry = "--dry-run" in sys.argv
    use_llm = "--no-llm" not in sys.argv
    DATA.mkdir(parents=True, exist_ok=True)

    boards = set(read_lines(COMPANIES)) | discover_boards(read_lines(QUERIES))
    boards = {b for b in boards if b.split(":", 1)[0] in FETCHERS}
    print(f"Checking {len(boards)} company boards.")

    listings = read_json(LISTINGS, [])
    seen = read_json(SEEN, {})
    names = read_json(NAMES, {})
    known = {normalize_url(l["url"]) for l in listings if l.get("url")} | set(seen)

    added, flagged, skipped = [], [], 0
    for board in sorted(boards):
        src, slug = board.split(":", 1)
        for job in FETCHERS[src](slug):
            key = normalize_url(job["url"]) if job.get("url") else None
            if not key or key in known or not passes_rules(job):
                continue
            known.add(key)
            seen[key] = datetime.now().strftime("%Y-%m-%d")  # remember rejects too
            company = company_name(src, slug, names)
            v = classify(job, company, use_llm)
            season = decide_season(v)
            if not season:
                skipped += 1
                continue
            added.append((make_listing(company, job, season), v))
            if v["season"] == "unclear":
                flagged.append(f"{company}: {job['title']}")
        time.sleep(0.3)

    print(f"{len(added)} new postings, {skipped} rejected, {len(flagged)} with unclear season.")
    if not added:
        return

    body = ["## New internship postings found by the bot", "",
            "Please review before merging. The model can be wrong. Company names come from the "
            "board (edit `.github/bot-data/company_names.json` to fix one for next time).", "",
            "| Company | Role | Goes to | Locations | Model note |", "| --- | --- | --- | --- | --- |"]
    for l, v in added:
        where = "Main README" if l["season"] == "Summer" else f"Off-season ({l['season']})"
        body.append(f"| {l['company_name']} | [{l['title']}]({l['url']}) | {where} | "
                    f"{', '.join(l['locations'])} | {v['reason']} |")
    if flagged:
        body += ["", "### Season unclear, defaulted to Summer. Check these:", ""] + [f"- {f}" for f in flagged]
    body += ["", f"Rejected by the filters this run: {skipped}"]

    if dry:
        print("\n".join(body))
        return

    listings.extend(l for l, _ in added)
    LISTINGS.write_text(json.dumps(listings, indent=4))
    SEEN.write_text(json.dumps(seen, indent=2, sort_keys=True))
    NAMES.write_text(json.dumps(names, indent=2, sort_keys=True))
    COMPANIES.write_text("# One board per line as source:slug (ashby, greenhouse, or lever).\n"
                         "# The bot appends boards it discovers.\n" + "\n".join(sorted(boards)) + "\n")
    PR_BODY.write_text("\n".join(body) + "\n")


if __name__ == "__main__":
    main()
