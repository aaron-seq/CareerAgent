# CareerAgent

A local AI-powered career assistant for personalized job outreach. This application automates the process of finding contacts, generating tailored email drafts, and managing your job search workflow using local LLMs.

## Features

- **Local LLM Integration**: Uses Ollama (Llama 3, Mistral, Qwen) for privacy-focused, zero-cost inference.
- **Job Discovery**: Integrated DuckDuckGo search for finding relevant job postings.
- **Contact Finder**: Automated search for hiring managers and contact permutation generation.
- **Personalized Outreach**: Generates technical, product, or impact-focused email drafts based on your CV and the job description.
- **Quality Assurance**: Built-in validation to ensure emails meet professional standards (no fluff, concrete metrics, clear CTA).
- **Multi-Channel Support**: Creates Gmail drafts directly or generates WhatsApp click-to-chat links.

## Technical Architecture

The application is built with a modern Python stack:

- **Frontend**: Streamlit for a responsive, interactive UI.
- **LLM Orchestration**: Custom Python client interacting with Ollama API.
- **Data Parsing**: PyPDF2 and PDFPlumber for robust CV extraction.
- **Search**: DuckDuckGo Search API for real-time contact and job data.
- **Storage**: Local filesystem storage with JSON serialization for privacy.

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Ollama installed and running (standard default port 11434)

### Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/aaron-seq/CareerAgent.git
    cd CareerAgent
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3.  Pull a model (e.g., Llama 3.1 8b):
    ```bash
    ollama pull llama3.1:8b
    ```

4.  Run the application:
    ```bash
    streamlit run app.py
    ```

## Deployment

The application is container-ready and supports deployment on platforms like Railway, Render, or Vercel (using docker).

### Docker

Build the container:

```bash
docker build -t careeragent .
docker run -p 8501:8501 careeragent
```

Note: For cloud deployment, ensure the Ollama instance is accessible or bundled within the container (requires significant resources).

## Project Structure

- `app.py`: Main entry point and UI logic.
- `core/`: Business logic modules (LLM, Parsers, Search).
- `assets/`: Static assets and styles.
- `requirements.txt`: Python dependencies.

## License

MIT License.
