"""
WhatsApp integration for click-to-chat links
Generates URL-encoded WhatsApp Web links with pre-filled messages
"""

from urllib.parse import quote
from typing import Optional


class WhatsAppClient:
    """Generate WhatsApp click-to-chat links"""

    def __init__(self):
        self.base_url = "https://wa.me"

    def create_click_to_chat_url(
        self, message: str, phone: Optional[str] = None
    ) -> str:
        """
        Create WhatsApp click-to-chat URL with pre-filled message

        Args:
            message: Message text to pre-fill
            phone: Phone number with country code (e.g., "1234567890")
                   If None, opens WhatsApp without specific contact

        Returns:
            WhatsApp Web URL
        """
        # URL encode message
        encoded_message = quote(message)

        if phone:
            # Remove non-numeric characters
            clean_phone = "".join(filter(str.isdigit, phone))
            # Create URL with specific contact
            url = f"{self.base_url}/{clean_phone}?text={encoded_message}"
        else:
            # Create URL without contact (user picks contact manually)
            url = f"{self.base_url}?text={encoded_message}"

        return url

    def validate_phone_number(self, phone: str) -> bool:
        """Validate phone number format"""
        if not phone:
            return False

        # Remove non-numeric characters
        clean = "".join(filter(str.isdigit, phone))

        # Phone should be 10-15 digits (country code + number)
        return 10 <= len(clean) <= 15

    def format_phone_number(self, phone: str) -> str:
        """Format phone number for WhatsApp (remove special chars)"""
        return "".join(filter(str.isdigit, phone))
