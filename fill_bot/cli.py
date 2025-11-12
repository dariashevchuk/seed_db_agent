import typer
import json
import glob
from ingest import build_index
from search import run_topic_search

app = typer.Typer()

@app.command()
def fill(topic_name: str, topics_file: str = "topics.json"):
    """
    Example:
      python app.py fill disinformation
    Looks up 'disinformation' in topics.json and processes all PDFs/DOCXs in root.
    """
    # Load topics.json from root
    with open(topics_file, "r", encoding="utf-8") as f:
        topics = json.load(f)

    # Find the topic by id or name
    topic = None
    for t in topics:
        if t["id"].lower() == topic_name.lower() or t["name"].lower() == topic_name.lower():
            topic = t
            break

    if not topic:
        typer.echo(f"Topic '{topic_name}' not found in {topics_file}")
        raise typer.Exit(code=1)

    # Collect all docs in root
    files = glob.glob("*.pdf") + glob.glob("*.docx")
    if not files:
        typer.echo("No PDF/DOCX files found in the root directory.")
        return

    for file_path in files:
        typer.echo(f"Indexing file: {file_path}")
        index_id = build_index(file_path)

        typer.echo(f"  → Processing topic: {topic['name']}")
        run_topic_search(topic, index_id, file_path)

if __name__ == "__main__":
    app()
