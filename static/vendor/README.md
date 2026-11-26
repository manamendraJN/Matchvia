# Vendored front-end libraries

Self-hosted so the CSP can stay `'self'` with no CDNs (CLAUDE.md, architecture 5 A03).
Update by downloading the npm tarball, checking it against the registry's `dist.integrity`,
and copying only the files listed here.

| Library | Version | Files | Source | Integrity (npm tarball) |
|---|---|---|---|---|
| htmx | 2.0.11 | `htmx/htmx.min.js`, `htmx/LICENSE` | `https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz` | checked against `dist.integrity` (sha512) on 2026-11-26 |
