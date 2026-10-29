"""Reading the caller's SimDB credentials from the MCP HTTP request."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from .client import AuthenticationError, Credentials


def credentials_from_headers(headers: Any) -> Credentials | None:
    """Return the HTTP Basic credentials in the Authorization header, or None if there is none.

    MCP clients are configured to send the user's ITER username and password this way;
    the server then logs in to SimDB as that user.
    """
    if not headers:
        return None
    value = headers.get("authorization") or headers.get("Authorization")
    if not value:
        return None
    scheme, _, encoded = value.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise AuthenticationError("The Authorization header must use the Basic scheme.")
    try:
        username, sep, password = base64.b64decode(encoded.strip()).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise AuthenticationError("The Authorization header is not valid Basic credentials.") from exc
    if not sep or not username:
        raise AuthenticationError("The Authorization header is not valid Basic credentials.")
    return Credentials(username, password)
