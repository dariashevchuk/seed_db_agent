from openai import OpenAI
import json, os

client = OpenAI()

def extract_with_llm(snippets, topic, file_path):
    prompt = f"""
    Topic: {topic['name']}
    Description: {topic['description']}
    Solutions: {topic['solutions']}

    From the text snippets below, extract any organizations or projects related
    to this topic. Return valid JSON with fields:
    - organization_id, name, description, website, contact_email
    - project_id, name, description, organization_id
    If nothing is found, return an empty array.
    Snippets:
    {snippets}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are an information extractor."},
                  {"role": "user", "content": prompt}],
        response_format={ "type": "json" }
    )

    data = response.choices[0].message.content

    # Append results to storage
    out_file = "fill_agent/extracted.json"
    if os.path.exists(out_file):
        existing = json.load(open(out_file, encoding="utf-8"))
    else:
        existing = []

    existing.append({"topic": topic["id"], "file": file_path, "data": json.loads(data)})
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
