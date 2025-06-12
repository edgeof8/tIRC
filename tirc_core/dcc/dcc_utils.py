import asyncio
# pyrc_core/dcc/dcc_utils.py
import socket
import struct
import logging
from typing import Tuple, Optional, List, Union
from pathlib import Path

logger = logging.getLogger("pyrc.dcc.utils")

def parse_dcc_address_and_port(address_str: str, port_str: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Parses DCC address and port strings. Handles both IPv4 and IPv6.
    Returns a tuple of (address, port) or (None, None) if parsing fails.
    """
    address = None
    port = None

    try:
        # Attempt to parse port first
        port = int(port_str)
        if not (1 <= port <= 65535):
            logger.warning(f"DCC port out of valid range: {port_str}")
            return None, None

        # Attempt to parse address as IPv4 (packed or dotted quad)
        try:
            # Try to unpack as a 4-byte IPv4 address
            packed_ip = int(address_str)
            address = socket.inet_ntoa(struct.pack('!I', packed_ip))
            logger.debug(f"Parsed IPv4 (packed) address: {address_str} -> {address}")
        except (ValueError, struct.error):
            # If not a packed IPv4, try as a dotted-quad IPv4 string
            try:
                socket.inet_pton(socket.AF_INET, address_str)
                address = address_str
                logger.debug(f"Parsed IPv4 (dotted quad) address: {address_str}")
            except socket.error:
                # If not IPv4, try as IPv6 (literal or bracketed)
                try:
                    # Remove brackets if present for IPv6 parsing
                    if address_str.startswith('[') and address_str.endswith(']'):
                        address_str = address_str[1:-1]
                    socket.inet_pton(socket.AF_INET6, address_str)
                    address = address_str
                    logger.debug(f"Parsed IPv6 address: {address_str}")
                except socket.error:
                    logger.warning(f"Could not parse DCC address '{address_str}' as IPv4 or IPv6.")
                    return None, None

    except ValueError:
        logger.warning(f"Invalid DCC port string: {port_str}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error parsing DCC address/port: {e}", exc_info=True)
        return None, None

    return address, port

def get_external_ip_address() -> Optional[str]:
    """
    Attempts to get the local machine's external IP address by connecting to a
    well-known STUN server or similar service. This is a best-effort approach.
    """
    # This is a common way to get *an* external IP, but it depends on
    # outbound connectivity and the target server being reachable.
    # It might return a local IP if NAT is involved.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Google's DNS server
        ip_address = s.getsockname()[0]
        s.close()
        logger.info(f"Determined external IP address: {ip_address}")
        return ip_address
    except Exception as e:
        logger.warning(f"Could not determine external IP address: {e}")
        return None

def get_local_ip_for_connection(target_host: str) -> Optional[str]:
    """
    Determines the local IP address that would be used to connect to a target host.
    This is useful for DCC SEND where the client needs to tell the recipient
    its IP address for the connection.
    """
    try:
        # Create a socket (doesn't actually connect)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Connect to a dummy address (doesn't send data)
        # This forces the kernel to pick an appropriate local IP for the target
        s.connect((target_host, 1))
        local_ip = s.getsockname()[0]
        s.close()
        logger.debug(f"Local IP for target {target_host}: {local_ip}")
        return local_ip
    except Exception as e:
        logger.warning(f"Could not determine local IP for target {target_host}: {e}")
        return None

def get_available_port(start_port: int, end_port: int) -> Optional[int]:
    """
    Finds an available port within a given range.
    """
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", port))
                return port
        except OSError:
            continue # Port is in use, try next
        except Exception as e:
            logger.error(f"Error checking port {port}: {e}")
            return None
    logger.warning(f"No available port found in range {start_port}-{end_port}")
    return None

def get_local_ip_for_ctcp(ip_address: str) -> str:
    """
    Formats a local IP address for inclusion in a DCC CTCP message.
    IPv4 addresses are packed into a long integer. IPv6 addresses are sent as-is.
    """
    try:
        # Try to pack as IPv4
        packed_ip = struct.unpack('!I', socket.inet_aton(ip_address))[0]
        return str(packed_ip)
    except (socket.error, struct.error):
        # If it's not IPv4, assume it's IPv6 (or invalid, but we'll send as-is)
        # IPv6 addresses are typically sent as literal strings, possibly bracketed
        return f"[{ip_address}]" if ":" in ip_address else ip_address

async def get_listening_socket(
    host: str, port: int, family: socket.AddressFamily = socket.AF_INET
) -> Optional[asyncio.Server]:
    """
    Attempts to create and return an asyncio listening socket.
    """
    try:
        server = await asyncio.start_server(lambda r, w: None, host=host, port=port, family=family)
        return server
    except OSError as e:
        logger.warning(f"Could not open listening socket on {host}:{port}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating listening socket: {e}", exc_info=True)
        return None

def is_valid_dcc_filename(filename: str) -> bool:
    """
    Checks if a filename is valid for DCC transfers (basic security check).
    Prevents path traversal and common problematic characters.
    """
    if not filename or filename.strip() == "":
        return False
    # Disallow path separators and control characters
    # On Windows, path separators are \ and /
    # On Unix-like, path separator is /
    # Also disallow null byte and other control chars
    invalid_chars = ['/', '\\', '\0', '\r', '\n', '\t']
    if any(c in filename for c in invalid_chars):
        return False
    # Disallow relative path components
    if ".." in filename or "./" in filename or ".\\" in filename:
        return False
    # Disallow leading/trailing whitespace
    if filename != filename.strip():
        return False
    return True

def get_safe_dcc_path(base_dir: str, filename: str) -> Optional[str]:
    """
    Constructs a safe file path for DCC transfers within a base directory.
    Prevents path traversal attacks.
    """
    if not is_valid_dcc_filename(filename):
        logger.warning(f"Attempted to create unsafe DCC filename: {filename}")
        return None

    # Use pathlib for robust path joining and resolution
    try:
        base_path = Path(base_dir).resolve()
        safe_path = (base_path / filename).resolve()

        # Ensure the resulting path is still within the base directory
        if not safe_path.is_relative_to(base_path):
            logger.warning(f"Path traversal detected: {safe_path} is not within {base_path}")
            return None
        return str(safe_path)
    except Exception as e:
        logger.error(f"Error creating safe DCC path for '{filename}' in '{base_dir}': {e}")
        return None
