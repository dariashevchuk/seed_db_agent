import fitz  # pymupdf
from docx import Document
from openai import OpenAI
import hashlib, os, sqlite3, json

client = OpenAI()

def file_id(path: str) -> str:
    return hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]

def build_index(file_path: str):
    doc_id = file_id(file_path)
    index_file = f"fill_agent/{doc_id}_index.json"

    if os.path.exists(index_file):
        return doc_id  # already indexed

    # Extract text
    if file_path.endswith(".pdf"):
        text = []
        with fitz.open(file_path) as pdf:
            for page in pdf:
                text.append(page.get_text())
        text = "\n".join(text)
    elif file_path.endswith(".docx"):
        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
    else:
        raise ValueError("Unsupported file type")

    # Chunk (naive split)
    chunks = [text[i:i+1500] for i in range(0, len(text), 1500)]

    # Embed
    embeddings = []
    for c in chunks:
        emb = client.embeddings.create(input=c, model="text-embedding-3-small").data[0].embedding
        embeddings.append({"text": c, "embedding": emb})

    # Save simple index as JSON
    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(embeddings, f)

    return doc_id
