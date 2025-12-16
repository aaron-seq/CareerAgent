# Contributing to CareerAgent

Thank you for your interest in contributing to CareerAgent! This document provides guidelines for contributing to the project.

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Ollama installed and running locally
- Git for version control

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/CareerAgent.git
   cd CareerAgent
   ```

3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Install Ollama and pull a model:
   ```bash
   ollama pull llama3.1:8b
   ```

6. Copy environment template:
   ```bash
   cp .env.example .env
   ```

## Development Workflow

### Branch Naming Convention

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions or modifications

Example: `feature/add-linkedin-integration`

### Making Changes

1. Create a new branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following the code style guidelines below

3. Test your changes locally:
   ```bash
   streamlit run app.py
   ```

4. Run tests (if available):
   ```bash
   pytest tests/
   ```

5. Commit your changes:
   ```bash
   git add .
   git commit -m "feat: add feature description"
   ```

### Commit Message Convention

Follow conventional commits:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Test additions or changes
- `chore:` - Maintenance tasks

Example:
```
feat: add WhatsApp integration for message drafts

- Implement WhatsAppClient class
- Add click-to-chat URL generation
- Update UI with WhatsApp draft button
```

## Code Style Guidelines

### Python Code Standards

- Follow PEP 8 style guide
- Use type hints where appropriate
- Maximum line length: 88 characters (Black formatter default)
- Use docstrings for all public functions and classes

### Docstring Format

```python
def function_name(param1: str, param2: int) -> bool:
    """
    Brief description of function.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When invalid input is provided
    """
    pass
```

### Code Organization

- Keep functions focused and under 50 lines
- Use Pydantic models for data structures
- Handle errors gracefully with try-except blocks
- Add logging for debugging (use print statements for now)

## Testing Guidelines

### Manual Testing Checklist

Before submitting a PR, test the following:

- [ ] Ollama connection works
- [ ] CV parsing from PDF works
- [ ] CV parsing from text works
- [ ] Job discovery search works
- [ ] Contact finder returns results
- [ ] Email draft generation works
- [ ] Draft quality validation works
- [ ] Gmail draft creation works (if configured)
- [ ] WhatsApp link generation works
- [ ] Data persistence in local storage
- [ ] Navigation between all pages works

### Unit Tests

If adding unit tests:

- Place tests in `tests/` directory
- Name test files as `test_module_name.py`
- Use pytest framework
- Mock external dependencies (Ollama, DuckDuckGo, Gmail API)

## Pull Request Process

1. Update README.md if you've added features
2. Ensure all manual tests pass
3. Update CHANGELOG.md with your changes (if exists)
4. Push to your fork and create a PR

### PR Title Format

```
[Type] Brief description
```

Examples:
- `[Feature] Add LinkedIn job scraper`
- `[Fix] Correct email validation logic`
- `[Docs] Update installation instructions`

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Code refactoring

## Testing
Describe testing performed

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Manual testing completed
- [ ] Documentation updated
```

## Core Modules Overview

### `core/llm.py`
Handles Ollama API communication, JSON parsing, retry logic

### `core/cv_parser.py`
Extracts structured data from CV PDFs using LLM

### `core/job_finder.py`
Searches for jobs using DuckDuckGo and extracts details

### `core/contact_finder.py`
Finds hiring managers and generates email permutations

### `core/personalization.py`
Generates personalized email drafts using LLM

### `core/validators.py`
Validates draft quality against professional standards

### `core/storage.py`
Handles local JSON-based persistence

### `core/gmail_drafts.py`
Creates Gmail drafts via Google API

### `core/models.py`
Pydantic data models for type safety

## Questions or Issues?

Feel free to:
- Open an issue for bugs or feature requests
- Start a discussion for questions
- Reach out via GitHub discussions

## Code of Conduct

- Be respectful and constructive
- Welcome newcomers and help them contribute
- Focus on improving the project
- Provide helpful feedback in code reviews

Thank you for contributing to CareerAgent!
