import logging
import os
import re
from typing import Dict, List, Union, Optional

# Assuming config.py will have these, or they will be passed to relevant functions.
# For now, let's define them here for standalone module clarity,
# but in integration, they'd come from the main config.
# from config import DCC_DOWNLOAD_DIR, DCC_BLOCKED_EXTENSIONS, DCC_MAX_FILE_SIZE

logger = logging.getLogger("pyrc.dcc.security")

# A more restrictive set of allowed characters for filenames.
# Allows alphanumerics, spaces, dots, underscores, hyphens, parentheses.
# Adjust as needed.
FILENAME_ALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9 ._()\-\[\]]")
MAX_FILENAME_LENGTH = 200 # Max length for a sanitized filename component

def sanitize_filename(filename: str, target_os: str = "posix") -> str:
    """
    Sanitizes a filename by removing potentially dangerous characters and patterns.
    Prevents directory traversal.

    Args:
        filename: The original filename.
        target_os: The target operating system ('posix' or 'windows') for OS-specific rules.
                   Defaults to 'posix' for more general safety.

    Returns:
        A sanitized filename string.
    """
    if not filename:
        return "_empty_filename_"

    # 1. Normalize path separators and remove leading/trailing whitespace
    base_name = os.path.basename(filename.strip())

    # 2. Handle OS-specific reserved names and characters
    if target_os == "windows":
        # Windows reserved names (case-insensitive)
        reserved_names = [
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        ]
        # Remove extension before checking reserved names
        name_part, ext_part = os.path.splitext(base_name)
        if name_part.upper() in reserved_names:
            base_name = f"_{base_name}"

        # Windows-specific illegal characters
        # ASCII 0-31 are generally problematic.
        # Characters: < > : " / \ | ? *
        # FILENAME_ALLOWED_CHARS will catch most of these, but explicit check is safer.
        base_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', base_name)
        # Remove trailing dots or spaces for Windows
        base_name = base_name.rstrip('. ')
        if not base_name: # if it became empty after stripping
            base_name = "_sanitized_empty_"

    # 3. Replace disallowed characters (using the stricter FILENAME_ALLOWED_CHARS)
    sanitized = FILENAME_ALLOWED_CHARS.sub('_', base_name)

    # 4. Collapse multiple underscores/hyphens/spaces resulting from substitution
    sanitized = re.sub(r'[_-\s]{2,}', '_', sanitized)
    sanitized = sanitized.strip('._- ') # Remove leading/trailing separators

    # 5. Enforce maximum length
    if len(sanitized) > MAX_FILENAME_LENGTH:
        name_part, ext_part = os.path.splitext(sanitized)
        # Try to preserve extension if possible
        if len(ext_part) < MAX_FILENAME_LENGTH / 2 and len(ext_part) > 0:
            name_part = name_part[:MAX_FILENAME_LENGTH - len(ext_part) -1] # -1 for the dot
            sanitized = f"{name_part}.{ext_part.lstrip('.')}"
        else:
            sanitized = sanitized[:MAX_FILENAME_LENGTH]

    # 6. Ensure filename is not empty after sanitization
    if not sanitized:
        sanitized = "_sanitized_" # Default if all chars were stripped

    # 7. Prevent filenames that are just "." or ".."
    if sanitized == "." or sanitized == "..":
        sanitized = f"_{sanitized}_"

    logger.debug(f"Sanitized filename '{filename}' to '{sanitized}'")
    return sanitized

def validate_download_path(
    requested_filename: str,
    download_dir: str,
    blocked_extensions: Optional[List[str]] = None,
    max_file_size: Optional[int] = None, # For checking against proposed size, not actual file
    proposed_file_size: Optional[int] = None
) -> Dict[str, Union[bool, str, None]]:
    """
    Validates a requested filename for download and constructs a safe, absolute path.

    Args:
        requested_filename: The filename proposed by the sender.
        download_dir: The configured base directory for downloads.
        blocked_extensions: A list of file extensions (e.g., ['.exe', '.bat']) to block.
        max_file_size: The maximum allowed file size in bytes.
        proposed_file_size: The filesize proposed by the sender.

    Returns:
        A dictionary:
        {
            "success": bool,
            "safe_path": Optional[str] (absolute path if successful, else None),
            "sanitized_filename": Optional[str],
            "error": Optional[str] (error message if not successful)
        }
    """
    if blocked_extensions is None:
        blocked_extensions = []

    # 1. Sanitize the filename component
    sanitized_name = sanitize_filename(requested_filename)
    if not sanitized_name: # Should be handled by sanitize_filename, but as a safeguard
        return {"success": False, "safe_path": None, "sanitized_filename": None, "error": "Filename became empty after sanitization."}

    # 2. Check for blocked file extensions
    _, ext = os.path.splitext(sanitized_name)
    if ext.lower() in [blocked.lower() for blocked in blocked_extensions]:
        logger.warning(f"Download blocked for '{requested_filename}' (sanitized: '{sanitized_name}') due to blocked extension: {ext}")
        return {"success": False, "safe_path": None, "sanitized_filename": sanitized_name, "error": f"File type '{ext}' is blocked."}

    # 3. Check proposed file size against max_file_size (if provided)
    if proposed_file_size is not None and max_file_size is not None:
        if proposed_file_size > max_file_size:
            logger.warning(f"Download blocked for '{requested_filename}' (size: {proposed_file_size}) exceeds max size ({max_file_size}).")
            return {"success": False, "safe_path": None, "sanitized_filename": sanitized_name, "error": f"File size {proposed_file_size} exceeds maximum allowed {max_file_size}."}

    # 4. Construct the full path and ensure it's within the download directory
    try:
        # Ensure download_dir is absolute and exists (or can be created)
        # This part should ideally be handled by DCCManager or config loader ensuring download_dir is valid
        abs_download_dir = os.path.abspath(download_dir)
        if not os.path.exists(abs_download_dir):
            try:
                os.makedirs(abs_download_dir, exist_ok=True)
                logger.info(f"Created download directory: {abs_download_dir}")
            except OSError as e:
                logger.error(f"Could not create download directory '{abs_download_dir}': {e}")
                return {"success": False, "safe_path": None, "sanitized_filename": sanitized_name, "error": f"Download directory '{abs_download_dir}' cannot be created."}

        # Join and normalize
        prospective_path = os.path.join(abs_download_dir, sanitized_name)
        abs_prospective_path = os.path.abspath(prospective_path)

        # Final check: ensure the absolute path of the file is still within the intended download directory
        # This helps prevent issues if sanitized_name somehow still had ".." or similar after sanitization,
        # or if download_dir was a symlink manipulated elsewhere.
        if os.path.commonprefix([abs_prospective_path, abs_download_dir]) != abs_download_dir:
            logger.error(f"Path traversal attempt detected or path mismatch: '{requested_filename}' -> '{abs_prospective_path}' is not within '{abs_download_dir}'.")
            return {"success": False, "safe_path": None, "sanitized_filename": sanitized_name, "error": "Invalid file path (potential traversal attempt)."}

        return {"success": True, "safe_path": abs_prospective_path, "sanitized_filename": sanitized_name, "error": None}

    except Exception as e:
        logger.error(f"Error during download path validation for '{requested_filename}': {e}", exc_info=True)
        return {"success": False, "safe_path": None, "sanitized_filename": sanitized_name, "error": f"Internal error validating path: {str(e)}"}


if __name__ == "__main__":
    # Test sanitize_filename
    print("--- Sanitize Filename Tests ---")
    filenames_to_test = [
        "file name.txt",
        "../../../../etc/passwd",
        "file<with>bad:chars?.txt",
        "COM1.txt",
        "file.with.dots.exe",
        " leading_space.dat",
        "trailing_space.dat ",
        "file_with_lots_of________________underscores.txt",
        "very_long_filename_that_should_be_truncated_and_hopefully_keeps_its_extension_if_it_is_not_too_long_itself.abcdef",
        "another_very_long_filename_without_any_extension_at_all_to_see_how_it_truncates_this_one_fully",
        ".bashrc",
        "..hidden_file",
        "",
        "NUL",
        "file.trailingdot."
    ]
    for fn in filenames_to_test:
        print(f"Original: '{fn}' -> Sanitized (posix): '{sanitize_filename(fn, 'posix')}'")
        print(f"Original: '{fn}' -> Sanitized (windows): '{sanitize_filename(fn, 'windows')}'")

    # Test validate_download_path
    print("\n--- Validate Download Path Tests ---")
    # Mock some config values for testing
    test_download_dir = "test_dcc_downloads" # Relative to current dir for test
    test_blocked_exts = [".exe", ".com"]
    test_max_size = 1000

    # Ensure test_download_dir exists for the test
    if not os.path.exists(test_download_dir):
        os.makedirs(test_download_dir, exist_ok=True)

    path_tests = [
        ("safe_file.txt", 500),
        ("evil.exe", 200),
        ("another_safe.dat", 2000), # Too large
        ("../outside_file.txt", 100), # Traversal attempt
        ("good_file_but_dir_is_bad/file.txt", 100) # Not really handled by this func directly, assumes download_dir is base
    ]

    for fn, size in path_tests:
        result = validate_download_path(
            fn,
            test_download_dir,
            blocked_extensions=test_blocked_exts,
            max_file_size=test_max_size,
            proposed_file_size=size
        )
        print(f"Validate '{fn}' (size {size}): {result}")

    # Clean up test directory
    # import shutil
    # if os.path.exists(test_download_dir):
    #     shutil.rmtree(test_download_dir)
