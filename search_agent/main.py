import argparse, json, os, time, logging
from urllib.parse import urlparse
from .queries_llm import generate_queries_via_openai
from .provider import SerpProvider
from .filters import is_drop, score_hit

def load_topics(path="topics.json"):
    with open(path, "r", encoding="utf-8") as f:
        arr = json.load(f)
    return {t["id"]: t for t in arr}

def run(topic_id: str, max_domains: int, outdir: str):
    logging.info(f"Starting run for topic_id={topic_id}")
    topics = load_topics()
    if topic_id not in topics:
        raise SystemExit(f"Unknown topic_id: {topic_id}")
    topic = topics[topic_id]
    logging.info(f"Generating queries for topic: {topic['name']}")
    queries = generate_queries_via_openai(topic)
    logging.info(f"Generated {len(queries)} queries")
    provider = SerpProvider(os.environ["SERPAPI_API_KEY"])
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{topic_id}.jsonl")
    seen_domains = set()
    scored = []
    for q in queries:
        logging.info(f"Searching for query: {q}")
        hits = provider.search(q, num=10)
        for rank, h in enumerate(hits, 1):
            url = h.get("link") or h.get("url")
            if not url: continue
            d = urlparse(url).netloc.lower()
            if d.startswith("www."): d = d[4:]
            if d in seen_domains: continue
            if is_drop(url, h, topic):
                logging.info(f"Dropping URL: {url}")
                continue
            s, reasons = score_hit(url, h, topic)
            scored.append((s, {
                "topic_id": topic_id,
                "query": q,
                "serp_rank": rank,
                "url": url,
                "domain": d,
                "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "is_directory": False,
                "confidence": round(s, 3),
                "reasons": reasons
            }))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    used = set()
    for _, item in scored:
        if item["domain"] in used: continue
        out.append(item); used.add(item["domain"])
        if len(used) >= max_domains: break
    with open(out_path, "w", encoding="utf-8") as f:
        for item in out:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    logging.info(f"Saved {len(out)} leads → {out_path}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument("topic_id")
    ap.add_argument("--max-domains", type=int, default=10)
    ap.add_argument("--outdir", default="data/leads")
    args = ap.parse_args()
    run(args.topic_id, args.max_domains, args.outdir)
