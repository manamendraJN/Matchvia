"""Build Tailwind CSS with the pinned standalone CLI (no Node.js, architecture D15).

    uv run python scripts/tailwind.py build    # minified build -> static/css/app.css
    uv run python scripts/tailwind.py watch    # rebuild on template changes (development)

On first use the CLI is downloaded from the official GitHub release into .tools/ and checked
against the SHA-256 below before it is ever executed. To upgrade, change VERSION and the
checksums (from the release's asset digests).
"""

import hashlib
import os
import platform

# subprocess runs only the checksum-verified Tailwind binary.
import subprocess  # nosec B404
import sys
import urllib.request
from pathlib import Path

VERSION = "v4.3.5"

# (sys.platform, machine) -> (release asset name, sha256)
ASSETS = {
    ("linux", "x86_64"): (
        "tailwindcss-linux-x64",
        "e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc",
    ),
    ("linux", "aarch64"): (
        "tailwindcss-linux-arm64",
        "ffcd0d21dbd7c605dc12743ff0c0b47debc963c86b399674084c1c8f2c96ecad",
    ),
    ("darwin", "arm64"): (
        "tailwindcss-macos-arm64",
        "f3f4f5d1727e2b693b8f1c9a1492b5dd87008c86ea286bee1589cb458e6235fc",
    ),
    ("darwin", "x86_64"): (
        "tailwindcss-macos-x64",
        "a63702686a3ed048b3135d84a73be49ea9d47f880c9b20e54b3ef60934ad8cdf",
    ),
    ("win32", "amd64"): (
        "tailwindcss-windows-x64.exe",
        "2803583268c53f4713e89943e211081fddb186c0a4a7d07b5c342c6ae853ec95",
    ),
}

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"
INPUT = ROOT / "assets" / "tailwind.css"
OUTPUT = ROOT / "static" / "css" / "app.css"


def asset() -> tuple[str, str]:
    machine = platform.machine().lower()
    machine = {"arm64": "aarch64"}.get(machine, machine) if sys.platform == "linux" else machine
    key = (sys.platform, machine)
    if key not in ASSETS:
        sys.exit(f"No pinned Tailwind CLI for {key}. Add it to ASSETS in {__file__}.")
    return ASSETS[key]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_cli() -> Path:
    name, expected = asset()
    binary = TOOLS / f"{VERSION}-{name}"
    if binary.is_file() and sha256(binary) == expected:
        return binary

    url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{VERSION}/{name}"
    print(f"Downloading Tailwind CLI {VERSION} ({name})...")
    TOOLS.mkdir(exist_ok=True)
    partial = binary.with_suffix(binary.suffix + ".part")
    # Fixed https URL to the official release; the file is verified before use.
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as fh:  # nosec B310
        while chunk := response.read(1 << 20):
            fh.write(chunk)

    actual = sha256(partial)
    if actual != expected:
        partial.unlink()
        sys.exit(f"Checksum mismatch for {name}: expected {expected}, got {actual}. Not run.")
    partial.replace(binary)
    binary.chmod(0o755)
    return binary


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode not in {"build", "watch"}:
        sys.exit("Usage: python scripts/tailwind.py [build|watch]")

    cli = ensure_cli()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    command = [str(cli), "--input", str(INPUT), "--output", str(OUTPUT)]
    command.append("--minify" if mode == "build" else "--watch")
    # Run from the repo root so @source paths resolve the same everywhere.
    result = subprocess.run(command, cwd=ROOT, check=False, env=os.environ.copy())  # noqa: S603  # nosec B603
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
