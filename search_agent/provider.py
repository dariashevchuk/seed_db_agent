import json, os, threading, logging
from serpapi import GoogleSearch

_LOCK = threading.Lock()

class SerpProvider:
    def __init__(self, api_key: str, cache_path: str = None):
        self.api_key = api_key
        self.cache_path = cache_path or os.path.join(os.path.dirname(__file__), "serp_cache.jsonl")
        self._cache = {}
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        self._cache[obj["q"]] = obj["results"]
                    except Exception:
                        continue

    def search(self, query: str, num: int = 10):
        if query in self._cache:
            logging.info(f"Cache hit for query: {query}")
            return self._cache[query]
        logging.info(f"Cache miss for query: {query}, fetching from SerpAPI")
        params = {"engine":"google","q":query,"num":num,"api_key":self.api_key}
        res = GoogleSearch(params).get_dict()
        hits = res.get("organic_results", []) or []
        with _LOCK:
            self._cache[query] = hits
            with open(self.cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"q":query,"results":hits}, ensure_ascii=False) + "\n")
            logging.info(f"Saved {len(hits)} results to cache for query: {query}")
        return hits
