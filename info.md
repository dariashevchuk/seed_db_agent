# Project: Seed DB Agent

## Project Description

This project is a command-line web scraping agent designed to gather information about non-profit organizations and their projects from specified websites. It uses a combination of web crawling, HTML parsing, and a Large Language Model (LLM) to extract structured data and save it into JSON files. The agent is built to be robust, handling various website structures and ensuring data quality through normalization and validation.

The agent starts with a given URL and systematically navigates through the website, following links that are within the same domain. For each page it visits, it takes a snapshot of the content, including HTML, Markdown, and JSON-LD data. This information is then passed to an LLM, which extracts details about the organization and its projects. The extracted data is then saved to `organizations.json` and `projects.json` files.

## Directory Tree

```
.
├── .gitignore
├── app.py
├── data
│   └── organizations.json
├── rag_agent
│   ├── fetch.py
│   ├── llm.py
│   ├── logging_setup.py
│   ├── models.py
│   ├── parse.py
│   └── storage.py
└── requirements.txt
```

## File Responsibilities

### `app.py`

The main entry point for the application. It provides a command-line interface (CLI) using `typer` that allows the user to start the web scraping process by providing a URL.

### `rag_agent/fetch.py`

This is the core of the web scraping logic. It uses `playwright` to navigate web pages, manage the crawling process, and extract data. Key responsibilities include:
- **Navigation**: Orchestrates the web crawling, managing a queue of URLs to visit.
- **Data Extraction**: Takes snapshots of web pages, including HTML, text content, and metadata.
- **State Management**: Keeps track of visited pages and the crawling frontier.

### `rag_agent/llm.py`

This module integrates with the OpenAI API to process the scraped data. Its main functions are:
- **Data Structuring**: Sends page content to the LLM to extract structured information about organizations and projects.
- **Content Expansion**: Uses the LLM to expand short descriptions into more detailed and coherent text.

### `rag_agent/parse.py`

A collection of utility functions for parsing and cleaning HTML content. It is responsible for:
- **HTML to Markdown**: Converts HTML into clean, readable Markdown.
- **Metadata Extraction**: Extracts titles, meta descriptions, and other metadata from HTML.
- **Link and Email Extraction**: Finds and normalizes URLs and email addresses from the page content.

### `rag_agent/storage.py`

Handles the storage and retrieval of the extracted data. Its key features include:
- **Data Persistence**: Saves the collected organization and project data to JSON files.
- **Atomic Writes**: Ensures that data is written to files safely, preventing corruption.
- **Upsert Logic**: Updates existing records or inserts new ones to avoid duplicates.

### `rag_agent/models.py`

Defines the data models for the application using `pydantic`. This ensures that all data structures are consistent and validated. Key models include:
- `Plan`: Defines the crawling strategy.
- `Snapshot`: Represents the data captured from a single web page.
- `OrganizationOut` and `ProjectOut`: Define the schema for the final output data.

### `rag_agent/logging_setup.py`

Configures the application's logging. It allows for setting the log level and directing log output to a file, which is useful for debugging and monitoring.

### `requirements.txt`

Lists all the Python dependencies required to run the project, such as `typer`, `playwright`, and `openai`.

### `.gitignore`

Specifies which files and directories should be ignored by version control (Git), such as `__pycache__` directories and other generated files.
