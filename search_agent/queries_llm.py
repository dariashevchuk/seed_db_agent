import os, json, hashlib, logging
from typing import List, Dict

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache_queries")
os.makedirs(CACHE_DIR, exist_ok=True)

def _key(topic: Dict) -> str:
    h = hashlib.sha256(json.dumps(topic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return h[:16]

def _path(k: str) -> str:
    return os.path.join(CACHE_DIR, f"{k}.json")

def _fallback(terms: List[str]) -> List[str]:
    tpls = [
        "({t}) site:.org OR site:.ngo inurl:/about OR inurl:/mission -job -vacancy -linkedin",
        "({t}) (nonprofit OR charity OR foundation OR fundacja OR фонд) -jobs -press",
        "site:.org ({t}) inurl:/donate OR \"support us\"",
    ]
    out = []
    for t in terms:
        for tpl in tpls:
            q = tpl.replace("{t}", t)
            if q not in out: out.append(q)
    return out[:12]

def generate_queries_via_openai(topic: Dict) -> List[str]:
    k = _key(topic)
    p = _path(k)
    if os.path.exists(p):
        logging.info(f"Cache hit for topic {topic['id']}, loading queries from {p}")
        return json.load(open(p, "r", encoding="utf-8"))
    logging.info(f"Cache miss for topic {topic['id']}, generating queries via OpenAI")
    terms = topic.get("terms") or []
    queries = None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        system = "Return strictly a JSON object with a single key 'queries' mapping to an array of 6-12 unique strings. Generate diverse, operator-rich web search queries that surface registered nonprofits addressing the topic. Prefer site: and inurl: operators, include 2-4 local-language variants when terms contain multiple languages, and avoid jobs/press/social."
        user = {"topic_id": topic["id"], "terms": terms}
        try:
            logging.info(f"Calling OpenAI with model {MODEL}")
            resp = client.responses.create(
                model=MODEL,
                input=[{"role":"system","content":system},{"role":"user","content":json.dumps(user, ensure_ascii=False)}],
                response_format={"type":"json_object"},
                temperature=0,
                max_output_tokens=600,
            )
            content = resp.output_text
            data = json.loads(content)
            queries = data.get("queries")
        except Exception as e:
            logging.warning(f"OpenAI API call failed, trying chat completion: {e}")
            m = [
                {"role":"system","content":system},
                {"role":"user","content":json.dumps(user, ensure_ascii=False)}
            ]
            resp = client.chat.completions.create(model=MODEL, messages=m, response_format={"type":"json_object"}, temperature=0)
            data = json.loads(resp.choices[0].message.content)
            queries = data.get("queries")
    except Exception as e:
        logging.error(f"Failed to generate queries via OpenAI: {e}")
        queries = None
    if not queries:
        logging.warning(f"No queries generated from OpenAI, using fallback for topic {topic['id']}")
        queries = _fallback(terms)
    queries = [q.strip() for q in queries if isinstance(q, str) and len(q.strip()) >= 8]
    uniq = []
    for q in queries:
        if q not in uniq: uniq.append(q)
    uniq = uniq[:12]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    logging.info(f"Saved {len(uniq)} queries to {p}")
    return uniq
