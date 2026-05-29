import requests
from bs4 import BeautifulSoup
import re
import json
import urllib.parse


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
        results = []
        if self.config.SERPAPI_KEY and self.provider in ("serpapi", "auto"):
            try:
                results = self._serpapi_search(query, max_results)
            except Exception:
                pass
        if not results and self.ddg is not None:
            try:
                results = self._duckduckgo_search(query, max_results)
            except Exception:
                pass
        if not results:
            try:
                results = self._google_scrape(query, max_results)
            except Exception:
                pass
        if not results:
            try:
                results = self._scrape_fallback(query, max_results)
            except Exception:
                pass
        return results

    def search_multi_source(self, query, max_results=5):
        all_results = []
        seen_urls = set()
        for provider_method in [self._serpapi_search, self._duckduckgo_search, self._google_scrape, self._scrape_fallback]:
            try:
                batch = provider_method(query, max_results)
                for r in batch:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
            except Exception:
                pass
            if len(all_results) >= max_results * 2:
                break
        return all_results[:max_results * 2]

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
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()
            for tag in soup.find_all(class_=re.compile(r"(sidebar|footer|nav|menu|comment|advertisement|ad-|social|share)")):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text)
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
        for r in results[:max_results]:
            r["content"] = self.fetch_page_content(r["url"], max_chars=6000)
        return results[:max_results]

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
