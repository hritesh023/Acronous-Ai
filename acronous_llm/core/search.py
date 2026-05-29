import requests
from bs4 import BeautifulSoup
import re

class WebSearch:
    def __init__(self, config):
        self.config = config
        self.provider = config.SEARCH_PROVIDER
        self.ddg = None
        self._init_search()

    def _init_search(self):
        if self.provider == "duckduckgo":
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
        if self.ddg is not None:
            return self._duckduckgo_search(query, max_results)
        return self._scrape_fallback(query, max_results)

    def _duckduckgo_search(self, query, max_results):
        try:
            results = list(self.ddg.text(query, max_results=max_results))
            parsed = []
            for r in results:
                parsed.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
            return parsed
        except Exception:
            return self._scrape_fallback(query, max_results)

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

    def fetch_page_content(self, url, max_chars=3000):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
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
