import re, logging
from urllib.parse import urlparse

SOCIAL = ("facebook.com","linkedin.com","twitter.com","x.com","instagram.com","youtube.com","tiktok.com")
BLOGGY = ("medium.com","blogspot.com","wordpress.com","substack.com")
JOBS = ("indeed","glassdoor","pracuj","nofluffjobs","lever.co","greenhouse.io")
NEWS = ("newsroom","/news","/press","/media")
DIR_HINTS = ("directory","list of","top charities","catalog","yellow pages","map")
ABOUT_HINTS = ("about","mission","donate","our-work","what-we-do","program","programs","projects","support")

def _netloc(u: str) -> str:
    d = urlparse(u).netloc.lower()
    if d.startswith("www."): d = d[4:]
    return d

def is_drop(url: str, hit: dict, topic: dict) -> bool:
    d = _netloc(url)
    if d.endswith(SOCIAL) or d.endswith(BLOGGY):
        logging.info(f"Dropping {url} due to social/bloggy domain")
        return True
    title = (hit.get("title") or "").lower()
    snip = (hit.get("snippet") or hit.get("snippet_highlighted_words") or "")
    if isinstance(snip, list): snip = " ".join(snip)
    snip = str(snip).lower()
    text = f"{title} {snip}"
    if any(k in d for k in JOBS):
        logging.info(f"Dropping {url} due to job-related keyword in domain")
        return True
    if any(k in url.lower() for k in NEWS):
        logging.info(f"Dropping {url} due to news-related keyword in URL")
        return True
    for r in topic.get("must_not", []):
        if re.search(r, text, re.I):
            logging.info(f"Dropping {url} due to 'must_not' rule: {r}")
            return True
    return False

def is_directory_hit(url: str, hit: dict) -> bool:
    title = (hit.get("title") or "").lower()
    snip = (hit.get("snippet") or "")
    if isinstance(snip, list): snip = " ".join(snip)
    snip = str(snip).lower()
    if any(k in title for k in ("wikipedia","wikidata")): return True
    if any(k in title or k in snip for k in DIR_HINTS): return True
    return False

def score_hit(url: str, hit: dict, topic: dict) -> tuple[float, list[str]]:
    reasons = []
    s = 0.5
    d = _netloc(url)
    if any(d.endswith(t) for t in topic.get("tld_bias", [])): 
        s += 0.2; reasons.append("tld_bias")
    p = urlparse(url).path.lower()
    if any(h in p for h in ABOUT_HINTS):
        s += 0.2; reasons.append("about_like_url")
    title = (hit.get("title") or "").lower()
    snip = (hit.get("snippet") or "")
    if isinstance(snip, list): snip = " ".join(snip)
    snip = str(snip).lower()
    txt = f"{title} {snip}"
    must = topic.get("must", [])
    if must and any(re.search(r, txt, re.I) for r in must):
        s += 0.1; reasons.append("must_match")
    if is_directory_hit(url, hit):
        s -= 0.3; reasons.append("directory_like")
    return max(0.0, min(1.0, s)), reasons
