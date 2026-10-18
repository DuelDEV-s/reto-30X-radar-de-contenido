"""Exa and Brave search APIs: LinkedIn discovery through their own indexes.

We never request linkedin.com. Each function returns results in rank order as
{"url", "title", "text", "published", "author"} dicts.
"""
import re

import httpx

from .. import config, db as store

BRAVE_COUNTRIES = {
    "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "HK", "IN", "ID", "IT",
    "JP", "KR", "MY", "MX", "NL", "NZ", "NO", "CN", "PL", "PT", "PH", "RU", "SA", "ZA", "ES",
    "SE", "CH", "TW", "TR", "GB", "US",
}
_TAG = re.compile(r"<[^>]+>")


def enabled_providers() -> list[str]:
    """Exa is required; Brave is an optional second index that adds recall when BRAVE_API_KEY is set."""
    return ["exa"] + (["brave"] if config.secret("BRAVE_API_KEY", required=False) else [])


class SearchSpend:
    """Tracks paid search calls across providers for the run's cost line."""

    def __init__(self):
        self.usd = 0.0
        self.calls = {"exa": 0, "brave": 0}


def exa_search(db, spend: SearchSpend, query: str, start_date: str, num_results: int = 25) -> list[dict]:
    key = f"{query}|{start_date[:10]}|{num_results}"
    cached = store.cache_get(db, "exa", key)
    if cached is not None:
        return cached
    r = httpx.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": config.secret("EXA_API_KEY"), "content-type": "application/json"},
        json={
            "query": query, "type": "auto", "numResults": num_results,
            "includeDomains": ["linkedin.com"], "startPublishedDate": start_date,
            "contents": {"text": {"maxCharacters": 2000}},
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    spend.calls["exa"] += 1
    spend.usd += (data.get("costDollars") or {}).get("total", config.EXA_USD_PER_SEARCH)
    out = [{"url": x.get("url", ""), "title": x.get("title") or "", "text": x.get("text") or "",
            "published": x.get("publishedDate"), "author": x.get("author")}
           for x in data.get("results", [])]
    store.cache_put(db, "exa", key, out)
    return out


def brave_search(db, spend: SearchSpend, keywords: str, lang: str, region: str | None,
                 date_from: str, date_to: str, count: int = 20) -> list[dict]:
    q = f"site:linkedin.com/posts {keywords}"
    country = region if region in BRAVE_COUNTRIES else "ALL"
    key = f"{q}|{lang}|{country}|{date_from}|{date_to}|{count}"
    cached = store.cache_get(db, "brave", key)
    if cached is not None:
        return cached
    r = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json",
                 "X-Subscription-Token": config.secret("BRAVE_API_KEY")},
        params={"q": q, "count": count, "country": country, "search_lang": lang,
                "freshness": f"{date_from}to{date_to}", "extra_snippets": "true"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    spend.calls["brave"] += 1
    spend.usd += config.BRAVE_USD_PER_QUERY
    out = []
    for x in (data.get("web") or {}).get("results", []):
        text = " ".join([x.get("description") or "", *(x.get("extra_snippets") or [])])
        out.append({"url": x.get("url", ""), "title": _TAG.sub("", x.get("title") or ""),
                    "text": _TAG.sub("", text).strip(), "published": x.get("page_age"),
                    "author": None})
    store.cache_put(db, "brave", key, out)
    return out
