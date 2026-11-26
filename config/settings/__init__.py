"""Settings modules (architecture 6.4).

base     shared by every environment; reads no secrets
dev      local development; loads .env
test     pytest (local and CI); loads .env if present
prod     production; every secret required from the real environment
staging  production settings with staging's own environment values
"""
