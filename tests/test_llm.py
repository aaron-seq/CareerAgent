"""Tests for LLM client module"""

from unittest.mock import Mock, patch

import pytest

from core.llm import CloudLLMClient, LocalLLMClient


class TestCloudLLMClient:
    """Test suite for the OpenAI-compatible cloud client"""

    def test_requires_api_key(self):
        """Empty/whitespace keys fail loudly instead of 401ing later"""
        with pytest.raises(ValueError):
            CloudLLMClient(api_key="")
        with pytest.raises(ValueError):
            CloudLLMClient(api_key="   ")

    def test_defaults_to_groq(self):
        client = CloudLLMClient(api_key="test-key")
        assert client.base_url == "https://api.groq.com/openai/v1"
        assert client.model == "openai/gpt-oss-120b"
        assert client._headers == {"Authorization": "Bearer test-key"}

    def test_trailing_slash_stripped(self):
        """Avoids '//models' when a base_url is pasted with a trailing slash"""
        client = CloudLLMClient(api_key="k", base_url="https://x.test/v1/")
        assert client.base_url == "https://x.test/v1"

    @patch("core.llm.requests.post")
    def test_generate_text_parses_openai_shape(self, mock_post):
        """Cloud response shape differs from Ollama's - unwrap choices[0]"""
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={"choices": [{"message": {"content": '  {"a": 1}  '}}]}
            ),
        )
        client = CloudLLMClient(api_key="k")
        assert client.generate_text("prompt") == '{"a": 1}'

    @patch("core.llm.requests.post")
    def test_bad_key_surfaces_actionable_error(self, mock_post):
        mock_post.return_value = Mock(status_code=401, text="unauthorized")
        client = CloudLLMClient(api_key="wrong")
        with pytest.raises(Exception, match="API key rejected"):
            client.generate_text("prompt")

    @patch("core.llm.requests.post")
    def test_rate_limit_surfaces_actionable_error(self, mock_post):
        mock_post.return_value = Mock(status_code=429, text="slow down")
        client = CloudLLMClient(api_key="k")
        with pytest.raises(Exception, match="rate limit"):
            client.generate_text("prompt")

    @patch("core.llm.requests.get")
    def test_list_models_unwraps_data(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"data": [{"id": "m1"}, {"id": "m2"}]}),
        )
        assert CloudLLMClient(api_key="k").list_models() == ["m1", "m2"]

    @patch("core.llm.requests.get")
    def test_check_connection_rejects_bad_key(self, mock_get):
        """A 401 is 'not connected', not an empty model list"""
        mock_get.return_value = Mock(status_code=401, text="unauthorized")
        client = CloudLLMClient(api_key="wrong")
        assert client.check_connection() is False
        assert client.list_models() == []

    @patch("core.llm.requests.get", side_effect=OSError("no network"))
    def test_check_connection_survives_transport_failure(self, mock_get):
        """Offline must return False, not raise into the Streamlit sidebar"""
        assert CloudLLMClient(api_key="k").check_connection() is False

    @patch("core.llm.requests.post")
    def test_inherits_json_pipeline(self, mock_post):
        """generate_json/schema logic is reused, not reimplemented"""
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]
                }
            ),
        )
        assert CloudLLMClient(api_key="k").generate_json("p") == {"ok": True}


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
        client = LocalLLMClient(base_url="http://custom:8000", model="mistral:7b")
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
        response = 'Here\'s the JSON: {"key": "value"}'
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
