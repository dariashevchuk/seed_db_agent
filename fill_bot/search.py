import json, numpy as np
from openai import OpenAI
from llm_extract import extract_with_llm

client = OpenAI()

def cosine(a, b):
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def run_topic_search(topic: dict, index_id: str, file_path: str):
    index_file = f"fill_agent/{index_id}_index.json"
    embeddings = json.load(open(index_file, encoding="utf-8"))

    results = []
    for term in topic["terms"]:
        query_emb = client.embeddings.create(input=term, model="text-embedding-3-small").data[0].embedding
        for chunk in embeddings:
            score = cosine(query_emb, chunk["embedding"])
            results.append((score, chunk["text"]))

    # sort and dedupe
    results = sorted(results, key=lambda x: x[0], reverse=True)[:5]
    snippets = [r[1] for r in results]

    extract_with_llm(snippets, topic, file_path)
