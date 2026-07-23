"""Tests for WhatsApp client module"""

from core.whatsapp import WhatsAppClient


class TestWhatsAppClient:
    """Test suite for WhatsAppClient"""

    def test_initialization(self):
        """Test WhatsApp client initialization"""
        client = WhatsAppClient()
        assert client.base_url == "https://wa.me"

    def test_create_click_to_chat_url_without_phone(self):
        """Test URL generation without phone number"""
        client = WhatsAppClient()
        message = "Hello, I am interested in the role."
        url = client.create_click_to_chat_url(message)

        assert url.startswith("https://wa.me?text=")
        assert "Hello" in url
        # Verify URL encoding of spaces
        assert "%20" in url or "+" in url

    def test_create_click_to_chat_url_with_phone(self):
        """Test URL generation with phone number"""
        client = WhatsAppClient()
        message = "Hello"
        phone = "+1234567890"
        url = client.create_click_to_chat_url(message, phone)

        assert "1234567890" in url
        assert url.startswith("https://wa.me/1234567890")

    def test_create_click_to_chat_url_phone_cleaning(self):
        """Test phone number cleaning in URL"""
        client = WhatsAppClient()
        message = "Test"
        phone = "+1 (234) 567-8900"
        url = client.create_click_to_chat_url(message, phone)

        # Phone should be stripped of non-numeric characters
        assert "12345678900" in url

    def test_validate_phone_number_valid(self):
        """Test phone validation with valid numbers"""
        client = WhatsAppClient()
        assert client.validate_phone_number("1234567890") is True
        assert client.validate_phone_number("+1234567890123") is True
        assert client.validate_phone_number("+1 234 567 8900") is True

    def test_validate_phone_number_invalid(self):
        """Test phone validation with invalid numbers"""
        client = WhatsAppClient()
        assert client.validate_phone_number("") is False
        assert client.validate_phone_number(None) is False
        assert client.validate_phone_number("123") is False  # Too short

    def test_format_phone_number(self):
        """Test phone number formatting"""
        client = WhatsAppClient()
        assert client.format_phone_number("+1 (234) 567-8900") == "12345678900"
        assert client.format_phone_number("1234567890") == "1234567890"
