# tirc_core/dcc/dcc_security.py
import os
import re
import logging
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger("tirc.dcc.security")

# Define a set of potentially dangerous characters for filenames, beyond OS limits
# This is a stricter set for cross-platform safety and to avoid issues with IRC/CTCP.
INVALID_FILENAME_CHARS = r'[\\/:*?"<>|\x00-\x1F\x7F]' # Includes control characters

# Maximum filename length (after sanitization)
MAX_FILENAME_LENGTH = 180 # A bit less than common OS limits (255) to be safe

def sanitize_filename(filename: str, target_os: Optional[str] = None) -> str:
    """
    Sanitizes a filename to remove or replace characters that are problematic
    for filesystems or for use in CTCP messages.
    - Replaces invalid characters with underscores.
    - Truncates to MAX_FILENAME_LENGTH.
    - Ensures it's not empty or just dots.
    """
    if not filename:
        return "_empty_filename_"

    # Replace invalid characters (control chars, slashes, etc.)
    sanitized = re.sub(INVALID_FILENAME_CHARS, "_", filename)

    # Remove leading/trailing dots and spaces (often problematic)
    sanitized = sanitized.strip(" .")

    # Truncate if too long
    if len(sanitized) > MAX_FILENAME_LENGTH:
        # Try to preserve extension if possible
        base, ext = os.path.splitext(sanitized)
        if ext and len(ext) < MAX_FILENAME_LENGTH / 2 : # Heuristic for valid extension
            base = base[:MAX_FILENAME_LENGTH - len(ext)]
            sanitized = base + ext
        else: # No extension or very long extension
            sanitized = sanitized[:MAX_FILENAME_LENGTH]

    # If sanitization results in an empty string or just dots, provide a default
    if not sanitized or all(c == '.' for c in sanitized):
        return "_sanitized_filename_"

    # OS-specific replacements (currently not implemented, but placeholder)
    # if target_os == "windows":
    #     # Windows specific checks like reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    #     pass
    # elif target_os == "linux" or target_os == "macos":
    #     pass

    logger.debug(f"Sanitized filename '{filename}' to '{sanitized}'")
    return sanitized


def is_path_safe(base_dir: Path, target_path: Path, allow_symlinks: bool = False) -> bool:
    """
    Checks if the target_path is safely within the base_dir.
    Prevents directory traversal attacks (e.g., '../../etc/passwd').
    """
    try:
        # Resolve both paths to their absolute, canonical forms
        # This handles '..' and symlinks (if not allowed explicitly)
        # For symlinks, if allow_symlinks is False (default), Path.resolve(strict=True)
        # will raise an error if any part of the path is a symlink.
        # If allow_symlinks is True, we resolve without strict=True, but this means
        # the resolved path might point outside if symlinks are cleverly used.
        # A truly robust symlink check would involve os.lstat and os.readlink iteratively.
        # For now, let's keep it simpler: if symlinks are disallowed, strict resolve is good.
        # If they are allowed, we rely on the common prefix check after non-strict resolve.

        resolved_base_dir = base_dir.resolve(strict=True) # Base must exist and not be a symlink itself

        # For target_path, if allow_symlinks is False, strict=True ensures no symlinks in path.
        # If allow_symlinks is True, we resolve without strict to get the final target,
        # but this means the check `commonpath` might be insufficient if symlinks point outside.
        # A truly secure handling of `allow_symlinks=True` is complex.
        # Given the context of DCC, disallowing symlinks by default (strict=True for target) is safer.
        # If allow_symlinks is explicitly True, the user accepts the risk or has other measures.
        resolved_target_path = target_path.resolve(strict=(not allow_symlinks))

        # Check if the resolved target path is a subpath of the resolved base directory
        # os.path.commonpath can be used, or checking if resolved_base_dir is a parent.
        is_subpath = resolved_target_path.is_relative_to(resolved_base_dir) # Python 3.9+
        # Fallback for older Python:
        # common = os.path.commonpath([resolved_base_dir, resolved_target_path])
        # is_subpath = (common == str(resolved_base_dir))

        if not is_subpath:
            logger.warning(f"Path traversal attempt or unsafe path: Target '{target_path}' (resolved: '{resolved_target_path}') is not within base '{base_dir}' (resolved: '{resolved_base_dir}').")
            return False

        # Additional check: ensure target_path doesn't try to escape via symlink even if resolved inside.
        # This is more relevant if allow_symlinks=True.
        # If not allowing symlinks, strict=True in resolve should have caught it.
        # This is a basic check; truly robust symlink handling is hard.
        if not allow_symlinks and target_path.is_symlink(): # Check original target_path too
             logger.warning(f"Target path '{target_path}' is a symlink, and symlinks are not allowed.")
             return False

        logger.debug(f"Path '{target_path}' (resolved: '{resolved_target_path}') is safe within '{base_dir}'.")
        return True

    except FileNotFoundError: # e.g. if base_dir doesn't exist, or part of target_path in strict mode
        logger.error(f"Path safety check failed: FileNotFoundError for base '{base_dir}' or target '{target_path}'.")
        return False
    except RuntimeError as e_resolve: # strict=True can raise RuntimeError if a path component is a symlink
        logger.warning(f"Path safety check failed for target '{target_path}' due to symlink (strict mode): {e_resolve}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during path safety check for '{target_path}': {e}", exc_info=True)
        return False


def get_safe_download_filepath(
    download_dir_str: str,
    requested_filename: str,
    blocked_extensions: Optional[Set[str]] = None,
    overwrite_existing: bool = False
) -> Optional[Path]:
    """
    Generates a safe, full filepath for a downloaded file.
    1. Sanitizes the filename.
    2. Checks against blocked extensions.
    3. Ensures the path is within the configured download directory.
    4. Handles filename collisions by appending a number if overwrite_existing is False.
    Returns a Path object or None if a safe path cannot be determined.
    """
    if blocked_extensions is None:
        blocked_extensions = set()

    base_download_dir = Path(download_dir_str).resolve() # Resolve once
    if not base_download_dir.is_dir():
        logger.error(f"DCC download directory '{base_download_dir}' does not exist or is not a directory.")
        try:
            base_download_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created DCC download directory: {base_download_dir}")
        except Exception as e:
            logger.error(f"Failed to create DCC download directory {base_download_dir}: {e}")
            return None


    sanitized_name = sanitize_filename(requested_filename)
    if not sanitized_name: # Should be handled by sanitize_filename returning a default
        logger.warning(f"Filename '{requested_filename}' sanitized to an empty string. Using default.")
        sanitized_name = "_downloaded_file_"

    # Check for blocked extensions
    file_ext = os.path.splitext(sanitized_name)[1].lower()
    if file_ext in blocked_extensions:
        logger.warning(f"DCC Download blocked: Filename '{sanitized_name}' has a blocked extension '{file_ext}'.")
        return None

    target_filepath = base_download_dir / sanitized_name

    # Path safety check (crucial)
    if not is_path_safe(base_download_dir, target_filepath):
        # is_path_safe already logs the warning
        return None

    # Handle filename collisions if not overwriting
    if not overwrite_existing:
        counter = 1
        original_target_filepath = target_filepath
        while target_filepath.exists():
            base, ext = os.path.splitext(original_target_filepath.name)
            # Ensure the new filename doesn't exceed max length with counter
            new_name_base = f"{base}({counter})"
            if len(new_name_base) + len(ext) > MAX_FILENAME_LENGTH:
                # If adding counter makes it too long, truncate base further
                available_len_for_base = MAX_FILENAME_LENGTH - len(ext) - len(f"({counter})")
                new_name_base = base[:available_len_for_base] + f"({counter})"

            target_filepath = base_download_dir / (new_name_base + ext)
            counter += 1
            if counter > 1000: # Safety break for extreme cases
                logger.error(f"Could not find a unique filename for '{original_target_filepath.name}' after 1000 attempts.")
                return None

    logger.info(f"Safe download path determined: {target_filepath}")
    return target_filepath
