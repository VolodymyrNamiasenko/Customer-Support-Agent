"""Validate untrusted upload names before accessing the filesystem."""
from pathlib import Path


def upload_path(root: str, filename: str | None) -> Path:
    if not filename or filename in {".", ".."}:
        raise ValueError("A filename is required.")
    if any(c in filename for c in ("/", "\\", "\x00")):
        raise ValueError("Filename must not contain path separators.")
    directory = Path(root).resolve()
    candidate = directory / filename
    if candidate.is_symlink() or candidate.resolve().parent != directory:
        raise ValueError("File must be inside the upload directory.")
    return candidate
