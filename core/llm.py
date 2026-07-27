"""
LLM clients: Ollama for local inference, plus an OpenAI-compatible cloud
client for hosted free tiers.
Handles JSON parsing, retries, and streaming
"""

import json
import time
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel


class LocalLLMClient:
    """Client for interacting with Ollama local LLM"""

    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "llama3.1:8b"
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = 120  # 2 minutes for large responses

    def check_connection(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = requests.get(f"{self.base_url}/api/version", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list:
        """List available models"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
            return []
        except Exception:
            return []

    def check_model_availability(self, model_name: str) -> bool:
        """Check if a specific model is available locally"""
        available_models = self.list_models()
        # Check for exact match or match with :latest
        if model_name in available_models:
            return True
        if f"{model_name}:latest" in available_models:
            return True
        return False

    def generate_text(
        self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000
    ) -> str:
        """Generate text response from LLM"""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }

            response = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                if response.status_code == 404:
                    raise Exception(
                        f"Model '{self.model}' not found. Please run `ollama pull {self.model}` in terminal."
                    )
                raise Exception(f"Ollama API error: {response.status_code}")

        except requests.exceptions.Timeout:
            raise Exception(
                "LLM request timed out. Try a smaller model or reduce prompt size."
            )
        except Exception as e:
            raise Exception(f"LLM generation failed: {str(e)}")

    def generate_json(
        self, prompt: str, temperature: float = 0.3, max_retries: int = 2
    ) -> Dict[str, Any]:
        """Generate JSON response with automatic parsing and retry logic"""

        for attempt in range(max_retries):
            try:
                # Add JSON formatting instruction
                json_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY valid JSON, no markdown, no explanations."

                # Generate response
                response_text = self.generate_text(
                    json_prompt, temperature=temperature, max_tokens=3000
                )

                # Clean response (remove markdown code blocks if present)
                cleaned = self._clean_json_response(response_text)

                # Parse JSON
                parsed = json.loads(cleaned)
                return parsed

            except json.JSONDecodeError as e:
                print(f"DEBUG: JSON Parse Error (Attempt {attempt + 1}): {e}")
                print(
                    f"DEBUG: Failed JSON content: {cleaned[:200]}..."
                )  # Print start of failed content
                if attempt < max_retries - 1:
                    # Retry with stricter prompt
                    time.sleep(1)
                    temperature *= (
                        0.5  # Lower temperature for more deterministic output
                    )
                    continue
                else:
                    raise Exception(
                        f"Failed to parse JSON after {max_retries} attempts."
                    )
            except Exception as e:
                raise Exception(f"LLM JSON generation failed: {str(e)}")

    def _clean_json_response(self, response: str) -> str:
        """Enhanced JSON extraction with better error handling"""
        response = response.strip()

        # Remove common preambles
        preambles = ["here's the json:", "here is the json:", "json:", "output:"]
        for pre in preambles:
            if response.lower().startswith(pre):
                response = response[len(pre) :].strip()

        # Remove markdown code blocks (more robust)
        if "```" in response:
            # Extract content between first and last ```
            parts = response.split("```")
            if len(parts) >= 3:
                # Take the middle part (between first and last ```)
                response = parts[1]
                # Remove language identifier (json, JSON, etc.)
                if response.strip().lower().startswith(("json")):
                    response = response.strip()[4:].strip()

        # Find JSON object boundaries (more precise)
        start = response.find("{")
        if start == -1:
            raise ValueError("No JSON object found in response")

        # Count braces to find matching closing brace
        brace_count = 0
        end = -1
        for i in range(start, len(response)):
            if response[i] == "{":
                brace_count += 1
            elif response[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break

        if end == -1:
            raise ValueError("Malformed JSON: no matching closing brace")

        return response[start:end]

    def generate_with_schema(
        self, prompt: str, schema_model: BaseModel, temperature: float = 0.3
    ) -> BaseModel:
        """Generate response and validate against Pydantic schema"""
        json_response = self.generate_json(prompt, temperature)

        try:
            validated = schema_model(**json_response)
            return validated
        except Exception as e:
            raise Exception(
                f"Response validation failed: {str(e)}\nResponse: {json_response}"
            )


# Default free-tier cloud endpoint. Groq is OpenAI-compatible and serves the
# same Llama family the local prompts are tuned for, so behaviour carries over.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class CloudLLMClient(LocalLLMClient):
    """OpenAI-compatible cloud client (Groq free tier by default).

    PRIVACY: unlike LocalLLMClient this sends prompt content off-machine.
    CLAUDE.md reserves cloud inference for non-PII work; using it for CV
    parsing or draft generation means resume data leaves the device.

    Only the three HTTP-touching methods differ from the Ollama client; the
    JSON cleaning, retry, and schema-validation logic is inherited unchanged.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = GROQ_BASE_URL,
        model: str = GROQ_DEFAULT_MODEL,
    ):
        if not api_key or not api_key.strip():
            raise ValueError(
                "No API key. Set GROQ_API_KEY in .env (get one free at "
                "https://console.groq.com/keys)."
            )
        super().__init__(base_url=base_url.rstrip("/"), model=model)
        self.api_key = api_key.strip()

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _fetch_models(self) -> Optional[list]:
        """GET /models -> model ids, or None if unreachable/key rejected.

        None and [] mean different things here: None is "couldn't ask",
        [] is "asked, key has no models".
        """
        try:
            response = requests.get(
                f"{self.base_url}/models", headers=self._headers, timeout=10
            )
            if response.status_code == 200:
                return [m["id"] for m in response.json().get("data", [])]
        except Exception:
            pass
        return None

    def check_connection(self) -> bool:
        """Verify the endpoint is reachable and the key is accepted"""
        return self._fetch_models() is not None

    def list_models(self) -> list:
        """List models the key has access to"""
        return self._fetch_models() or []

    def generate_text(
        self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000
    ) -> str:
        """Generate text via the chat-completions endpoint.

        JSON mode mirrors the Ollama client's hardcoded `format: json`. Every
        caller reaches this through generate_json(), whose prompt already
        contains the word "json" that OpenAI-compatible JSON mode requires.
        """
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }

            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            if response.status_code == 401:
                raise Exception("API key rejected. Check GROQ_API_KEY in .env.")
            if response.status_code == 404:
                raise Exception(
                    f"Model '{self.model}' not available on this endpoint. "
                    "Cloud providers retire models; pick a current one."
                )
            if response.status_code == 429:
                raise Exception(
                    "Free-tier rate limit hit. Wait for the quota window to "
                    "reset, or switch to a local Ollama model."
                )
            raise Exception(
                f"Cloud API error {response.status_code}: {response.text[:200]}"
            )

        except requests.exceptions.Timeout:
            raise Exception(
                "LLM request timed out. Try a smaller model or reduce prompt size."
            )
        except Exception as e:
            raise Exception(f"LLM generation failed: {str(e)}")
