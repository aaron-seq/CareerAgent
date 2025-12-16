"""Tests for LLM client module"""
import pytest
from unittest.mock import Mock, patch
from core.llm import LocalLLMClient


class TestLocalLLMClient:
    """Test suite for LocalLLMClient"""

    def test_initialization(self):
        """Test LLM client initialization with default parameters"""
        client = LocalLLMClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3.1:8b"
        assert client.timeout == 120

    def test_custom_initialization(self):
        """Test LLM client initialization with custom parameters"""
        client = LocalLLMClient(
            base_url="http://custom:8000", model="mistral:7b"
        )
        assert client.base_url == "http://custom:8000"
        assert client.model == "mistral:7b"

    @patch("core.llm.requests.get")
    def test_check_connection_success(self, mock_get):
        """Test successful connection check"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = LocalLLMClient()
        assert client.check_connection() is True

    @patch("core.llm.requests.get")
    def test_check_connection_failure(self, mock_get):
        """Test failed connection check"""
        mock_get.side_effect = Exception("Connection refused")

        client = LocalLLMClient()
        assert client.check_connection() is False

    def test_clean_json_response_basic(self):
        """Test basic JSON response cleaning"""
        client = LocalLLMClient()
        response = '{"key": "value"}'
        cleaned = client._clean_json_response(response)
        assert cleaned == '{"key": "value"}'

    def test_clean_json_response_with_markdown(self):
        """Test JSON response cleaning with markdown code blocks"""
        client = LocalLLMClient()
        response = '```json\n{"key": "value"}\n```'
        cleaned = client._clean_json_response(response)
        assert cleaned == '{"key": "value"}'

    def test_clean_json_response_with_preamble(self):
        """Test JSON response cleaning with preamble text"""
        client = LocalLLMClient()
        response = "Here's the JSON: {\"key\": \"value\"}"
        cleaned = client._clean_json_response(response)
        assert cleaned == '{"key": "value"}'

    def test_clean_json_response_no_json(self):
        """Test JSON response cleaning with no JSON object"""
        client = LocalLLMClient()
        response = "This is just text"
        with pytest.raises(ValueError, match="No JSON object found"):
            client._clean_json_response(response)

    @patch("core.llm.requests.get")
    def test_list_models(self, mock_get):
        """Test listing available models"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.1:8b"}, {"name": "mistral:7b"}]
        }
        mock_get.return_value = mock_response

        client = LocalLLMClient()
        models = client.list_models()
        assert len(models) == 2
        assert "llama3.1:8b" in models
        assert "mistral:7b" in models
