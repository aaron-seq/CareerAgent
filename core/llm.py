"""
Ollama LLM client for local inference
Handles JSON parsing, retries, and streaming
"""

import json
import requests
from typing import Optional, Dict, Any
import time
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
        except:
            return False

    def list_models(self) -> list:
        """List available models"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
            return []
        except:
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
