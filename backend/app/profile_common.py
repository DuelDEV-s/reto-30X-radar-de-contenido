"""Shared normalization and sanitized provider errors."""
import re


class ProviderError(Exception):
    def __init__(self, message, status="error", code="provider_error"):
        self.message, self.status, self.code = message, status, code


def clean_text(value, limit=3000):
    text = value[:limit] if isinstance(value, str) else ""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", text)
    return re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[teléfono omitido]", text)


def number(value):
    if value is None or isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    try:
        # Ambiguous strings such as '1.2K' are deliberately left unknown.
        result = int(value)
        return result if 0 <= result <= 10**15 else None
    except (ValueError, TypeError, OverflowError):
        return None
