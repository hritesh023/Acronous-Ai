import requests
from bs4 import BeautifulSoup
import re
import json
import urllib.parse
import random
import logging

logger = logging.getLogger(__name__)

SEARXNG_URLS = [
    'https://searx.be/search', 'https://search.sapti.me/search',
    'https://searx.tuxcloud.net/search', 'https://searx.work/search',
    'https://searx.info/search', 'https://search.mdosch.de/search',
    'https://searx.xyz/search', 'https://searx.no/search',
]


class WebSearch:
    def __init__(self, config):
        self.config = config
        self.provider = config.SEARCH_PROVIDER
        self.ddg = None
        self._init_search()

    def _init_search(self):
        if self.provider in ("duckduckgo", "auto"):
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=RuntimeWarning)
                    from ddgs import DDGS
                self.ddg = DDGS()
            except Exception:
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=RuntimeWarning)
                        from duckduckgo_search import DDGS
                    self.ddg = DDGS()
                except Exception:
                    self.ddg = None
        elif self.provider == "serpapi":
            self.serpapi_key = self.config.SERPAPI_KEY

    def search(self, query, max_results=5):
        """Multi-engine search — tries DuckDuckGo, SearXNG, Wikipedia, Google News, Hacker News in parallel."""
        import concurrent.futures

        engines = [
            ("duckduckgo", self._duckduckgo_search),
            ("searxng", self._searxng_search),
            ("wikipedia", self._wikipedia_search),
            ("google_news_rss", self._google_news_rss_search),
            ("hackernews", self._hackernews_search),
            ("google", self._google_scrape),
        ]

        all_results = []
        seen_urls = set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fn, query, max_results): name for name, fn in engines}
            for future in concurrent.futures.as_completed(futures, timeout=10):
                name = futures[future]
                try:
                    results = future.result()
                    for r in results:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append(r)
                except Exception:
                    pass

        return all_results[:max_results]

    def search_multi_source(self, query, max_results=5):
        return self.search(query, max_results)

    def _searxng_search(self, query, max_results):
        """Search via public SearXNG instances (free, unlimited, no API key)."""
        shuffled = SEARXNG_URLS[:]
        random.shuffle(shuffled)
        for url in shuffled:
            try:
                u = urllib.parse.urlparse(url)
                params = urllib.parse.urlencode({
                    'q': query, 'format': 'json', 'language': 'en', 'pageno': '1',
                })
                search_url = f"{u.scheme}://{u.netloc}{u.path}?{params}"
                resp = requests.get(search_url, headers={
                    'Accept': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                }, timeout=5)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                results = []
                for item in (data.get("results") or [])[:max_results]:
                    title = item.get("title", "")
                    url_r = item.get("url", "")
                    snippet = item.get("content", "")[:200]
                    if title and url_r:
                        results.append({"title": title, "url": url_r, "snippet": snippet})
                if results:
                    return results
            except Exception:
                continue
        return []

    def _wikipedia_search(self, query, max_results=3):
        """Search Wikipedia API — always free, reliable, high quality."""
        try:
            sr = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": max_results},
                headers={"User-Agent": "NavigwizAI/2.0"},
                timeout=5,
            )
            if sr.status_code != 200:
                return []
            data = sr.json()
            titles = [s["title"] for s in data.get("query", {}).get("search", [])]
            results = []
            for title in titles[:max_results]:
                try:
                    pr = requests.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}",
                        headers={"User-Agent": "NavigwizAI/2.0"},
                        timeout=4,
                    )
                    if pr.status_code == 200:
                        page = pr.json()
                        if page.get("extract"):
                            results.append({
                                "title": page["title"],
                                "url": page.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"),
                                "snippet": page["extract"][:500],
                            })
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def _google_news_rss_search(self, query, max_results=3):
        """Google News RSS — free, fresh news results."""
        try:
            resp = requests.get(
                f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en&gl=US&ceid=US:en",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=6,
            )
            if resp.status_code != 200:
                return []
            items = re.findall(r'<item>[\s\S]*?</item>', resp.text)
            results = []
            seen = set()
            for item in items[:max_results * 2]:
                title_m = re.search(r'<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>', item)
                link_m = re.search(r'<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/link>', item)
                if title_m:
                    title = title_m.group(1).strip()
                    link = link_m.group(1).strip() if link_m else ""
                    if title and title not in seen:
                        seen.add(title)
                        results.append({"title": title, "url": link, "snippet": ""})
                        if len(results) >= max_results:
                            break
            return results
        except Exception:
            return []

    def _hackernews_search(self, query, max_results=3):
        """Hacker News via Algolia — free, great for tech topics."""
        try:
            resp = requests.get(
                f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}&hitsPerPage={max_results}&tags=story",
                timeout=5,
            )
            if resp.status_code != 200:
                return []
            hits = resp.json().get("hits", [])
            return [{"title": h.get("title", ""), "url": h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"), "snippet": ""} for h in hits[:max_results]]
        except Exception:
            return []

    def _serpapi_search(self, query, max_results):
        params = {
            "q": query,
            "api_key": self.config.SERPAPI_KEY,
            "num": max_results,
            "engine": "google",
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = resp.json()
        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results

    def _duckduckgo_search(self, query, max_results):
        results = list(self.ddg.text(query, max_results=max_results))
        parsed = []
        for r in results:
            parsed.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        return parsed

    def _google_scrape(self, query, max_results):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&num={max_results}"
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for g in soup.select("div.g"):
            link = g.select_one("a")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                continue
            title_el = g.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet_el = g.select_one("div[data-sncf], span.aCOpRe, div.VwiC3b")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title and href:
                results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results

    def _scrape_fallback(self, query, max_results):
        try:
            url = "https://lite.duckduckgo.com/lite/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = {"q": query}
            resp = requests.post(url, data=data, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for table in soup.select("table"):
                for row in table.select("tr"):
                    link = row.select_one("a")
                    if not link:
                        continue
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    if not title or not href or href.startswith("/"):
                        continue
                    snippet_td = link.find_parent("td")
                    snippet = ""
                    if snippet_td:
                        snippet_td = snippet_td.find_next_sibling("td")
                        if snippet_td:
                            snippet = snippet_td.get_text(strip=True)
                    results.append({
                        "title": title,
                        "url": href,
                        "snippet": snippet,
                    })
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
            return results
        except Exception:
            return []

    def fetch_page_content(self, url, max_chars=4000):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "form", "button"]):
                tag.decompose()
            for tag in soup.find_all(class_=re.compile(r"(sidebar|footer|nav|menu|comment|advertisement|ad-|social|share|cookie|banner|modal|overlay)")):
                tag.decompose()
            for selector in ["main", "article", "[role=main]", ".content", ".post", ".entry", ".article-body"]:
                section = soup.select_one(selector)
                if section:
                    text = section.get_text(separator=" ", strip=True)
                    if len(text) > 200:
                        text = re.sub(r'\s+', ' ', text)
                        return text[:max_chars]
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text)
            lines = [l.strip() for l in text.split(". ") if len(l.strip()) > 30]
            if lines:
                text = ". ".join(lines)
            return text[:max_chars]
        except Exception:
            return ""

    def search_with_content(self, query, max_results=3):
        results = self.search(query, max_results)
        for r in results:
            r["content"] = self.fetch_page_content(r["url"])
        return results

    def search_with_deep_content(self, query, max_results=3):
        results = self.search_multi_source(query, max_results)
        enriched = []
        for r in results[:max_results]:
            r["content"] = self.fetch_page_content(r["url"], max_chars=6000)
            enriched.append(r)
            if len(enriched) >= max_results:
                break
        if not enriched:
            results = self.search(query, max_results + 2)
            for r in results[:max_results]:
                r["content"] = self.fetch_page_content(r["url"], max_chars=6000)
                enriched.append(r)
                if len(enriched) >= max_results:
                    break
        return enriched[:max_results]

    def fetch_current_time(self):
        try:
            results = self.search("current date and time right now", max_results=3)
            snippets = [r.get("snippet", "") for r in results if r.get("snippet")]
            if snippets:
                return "\n".join(snippets[:2])
            content_parts = []
            for r in results:
                c = r.get("content", "")
                if c:
                    content_parts.append(c[:500])
            if content_parts:
                return "\n".join(content_parts[:2])
        except Exception:
            pass
        return ""

    def fetch_current_location(self):
        try:
            results = self.search("what is my location ip address", max_results=3)
            snippets = [r.get("snippet", "") for r in results if r.get("snippet")]
            if snippets:
                return "\n".join(snippets[:2])
            content_parts = []
            for r in results:
                c = r.get("content", "")
                if c:
                    content_parts.append(c[:500])
            if content_parts:
                return "\n".join(content_parts[:2])
        except Exception:
            pass
        return ""
