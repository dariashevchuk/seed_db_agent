import os
from openai import OpenAI

def expand_to_ua_description(source_md: str, fallback_text: str = "", min_chars: int = 600, model: str = "gpt-4o-mini") -> str:
    """
    Turn scraped Markdown (plus fallback text) into a coherent Ukrainian description.
    Requires OPENAI_API_KEY in the environment.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=api_key)

    base = (source_md or "").strip()
    if not base and fallback_text:
        base = fallback_text.strip()

    prompt = f"""
Використай наведений матеріал (Markdown нижче) і підготуй зв'язний опис українською мовою
(мінімум {min_chars} символів). 
Стиль: інформативний, без маркетингових перебільшень. Якщо трапляються англіцизми — переклади.
Не вигадуй фактів, опирайся лише на матеріал.

=== МАТЕРІАЛ ===
{base}
"""

    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": "Ти помічник, який пише стислі, точні описи українською."},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()
