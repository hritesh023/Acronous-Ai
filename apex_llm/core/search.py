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
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for r in soup.select(".result")[:max_results]:
                title_el = r.select_one(".result__title a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": title_el.get("href", ""),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else ""
                    })
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
