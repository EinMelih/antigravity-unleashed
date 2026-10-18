"""
Antigravity Headless Client & Reverse Engineering Toolkit
Zero-CDP native Python client and CLI communicating directly with
Google Antigravity Language Server via Connect Protocol over loopback HTTPS.
"""

from .client import AntigravityClient, LanguageServerError, AuthenticationError

__version__ = "2.24.0"
__all__ = ["AntigravityClient", "LanguageServerError", "AuthenticationError"]
