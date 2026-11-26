"""Staging settings: production settings with staging's own environment values.

Staging uses different values for every secret and sits behind Cloudflare Access.
The SMS number allowlist is added here in S12.
"""

from .prod import *
