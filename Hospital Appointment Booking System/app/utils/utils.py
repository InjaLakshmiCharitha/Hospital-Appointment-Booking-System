
import uuid
from pathlib import Path

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".png"}


def validate_file_extension(filename: str) -> str:
    """Validate the uploaded file extension."""
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Only PDF, JPG and PNG files are allowed")

    return extension


def validate_file_size(content: bytes) -> None:
    """Reject empty files and files larger than 5 MB."""
    if not content:
        raise ValueError("Empty files are not allowed")

    if len(content) > MAX_FILE_SIZE:
        raise OverflowError("Maximum file size is 5 MB")


def validate_file_content(content: bytes, extension: str) -> None:
    """Check that the file content matches its extension."""
    valid_signatures = {
        ".pdf": content.startswith(b"%PDF-"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
    }

    if not valid_signatures.get(extension.lower(), False):
        raise ValueError(
            "File content does not match the file extension"
        )


def generate_unique_filename(extension: str) -> str:
    """Generate a unique filename to prevent filename collisions."""
    extension = extension.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file extension")

    return f"{uuid.uuid4().hex}{extension}"
