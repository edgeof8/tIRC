# tirc_core/dcc/dcc_utils.py
import socket
import logging
import ipaddress
import re # Added import for re
from typing import Optional, Tuple, Dict, Any

from tirc_core.config_defs import DccConfig

logger = logging.getLogger("tirc.dcc.utils")

def get_local_ip_for_ctcp(dcc_config: DccConfig, event_logger: Optional[logging.Logger] = None) -> str:
    """
    Determines the local IP address to advertise for DCC CTCP,
    considering a manually configured dcc_advertised_ip.
    """
    effective_logger = event_logger or logger

    if dcc_config.advertised_ip:
        try:
            ipaddress.ip_address(dcc_config.advertised_ip)
            effective_logger.info(f"Using configured advertised_ip: {dcc_config.advertised_ip}")
            return dcc_config.advertised_ip
        except ValueError:
            effective_logger.warning(
                f"Configured advertised_ip '{dcc_config.advertised_ip}' is invalid. Attempting auto-detection."
            )

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        effective_logger.info(f"Auto-detected local IP for DCC: {local_ip}")
        return local_ip
    except socket.gaierror as e:
        effective_logger.error(f"Socket gaierror during IP auto-detection (e.g. no internet): {e}. Falling back to gethostbyname.")
    except socket.error as e:
        effective_logger.error(f"Socket error during IP auto-detection: {e}. Falling back to gethostbyname.")

    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip == "127.0.0.1":
            all_ips = socket.gethostbyname_ex(hostname)[2]
            non_localhost_ips = [ip for ip in all_ips if ip != "127.0.0.1" and not ip.startswith("169.254")]
            if non_localhost_ips:
                local_ip = non_localhost_ips[0]
            else:
                local_ip = all_ips[0] if all_ips else "127.0.0.1"
        effective_logger.info(f"Fallback auto-detected local IP for DCC: {local_ip}")
        return local_ip
    except socket.gaierror:
        effective_logger.critical("Failed to auto-detect local IP address for DCC. Using 127.0.0.1 as last resort.")
        return "127.0.0.1"

def find_available_port(start_port: int, end_port: int, host: str = "0.0.0.0") -> Optional[int]:
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                logger.debug(f"Port {port} is available.")
                return port
        except socket.error:
            logger.debug(f"Port {port} is in use or unavailable.")
            continue
    logger.warning(f"No available port found in range {start_port}-{end_port}.")
    return None

async def create_listening_socket(host: str, port: int) -> Optional[socket.socket]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(1)
        sock.setblocking(False)
        logger.info(f"DCC listening socket created on {host}:{port}")
        return sock
    except socket.error as e:
        logger.error(f"Failed to create listening socket on {host}:{port}: {e}")
        return None

def format_dcc_ctcp(command: str, filename: str, ip_int: int, port: int, size: int, token: Optional[str]=None) -> str:
    if token:
        return f"DCC {command} \"{filename}\" {token} {size}"
    else:
        return f"DCC {command} \"{filename}\" {ip_int} {port} {size}"

def parse_dcc_ctcp(message: str) -> Optional[Dict[str, Any]]:
    match = re.match(r'DCC\s+([A-Z]+)\s+(?:"([^"]+)"|([^\s]+))\s*(.*)', message, re.IGNORECASE)
    if not match:
        logger.debug(f"Not a DCC message or malformed (regex fail): {message}")
        return None

    command = match.group(1).upper()
    filename_quoted = match.group(2)
    filename_unquoted = match.group(3)
    remaining_args_str = match.group(4).strip()

    filename = filename_quoted if filename_quoted is not None else filename_unquoted
    if not filename:
        logger.warning(f"Could not parse filename from DCC message (regex internal): {message}")
        return None

    other_params = remaining_args_str.split()
    parsed_data: Dict[str, Any] = {"command": command, "filename": filename}

    if command == "SEND":
        if len(other_params) == 3:
            try:
                parsed_data["ip_int"] = int(other_params[0])
                parsed_data["port"] = int(other_params[1])
                parsed_data["filesize"] = int(other_params[2])
                parsed_data["ip_str"] = socket.inet_ntoa(int(other_params[0]).to_bytes(4, 'big'))
                parsed_data["is_passive"] = False
            except (ValueError, IndexError, OverflowError, socket.error) as e:
                logger.warning(f"Malformed active DCC SEND: {message} - {e}")
                return None
        elif len(other_params) == 2:
            try:
                parsed_data["token"] = other_params[0]
                parsed_data["filesize"] = int(other_params[1])
                parsed_data["is_passive"] = True
            except (ValueError, IndexError) as e:
                logger.warning(f"Malformed passive DCC SEND: {message} - {e}")
                return None
        else:
            logger.warning(f"Malformed DCC SEND (expected 3 or 2 params after filename): {message}")
            return None
    elif command == "GET":
        if len(other_params) == 1:
            parsed_data["token"] = other_params[0]
        else:
            logger.warning(f"Malformed DCC GET (expected 1 param after filename): {message}")
            return None
    elif command == "ACCEPT":
        if len(other_params) == 2:
            try:
                parsed_data["token"] = other_params[0]
                parsed_data["port"] = int(other_params[1])
            except (ValueError, IndexError) as e:
                logger.warning(f"Malformed DCC ACCEPT: {message} - {e}")
                return None
        else:
            logger.warning(f"Malformed DCC ACCEPT (expected 2 params after filename): {message}")
            return None
    elif command == "RESUME":
        if len(other_params) == 2:
            try:
                parsed_data["port"] = int(other_params[0])
                parsed_data["position"] = int(other_params[1])
            except (ValueError, IndexError) as e:
                logger.warning(f"Malformed DCC RESUME: {message} - {e}")
                return None
        else:
            logger.warning(f"Malformed DCC RESUME (expected 2 params after filename): {message}")
            return None
    else:
        logger.warning(f"Unsupported DCC command '{command}' in CTCP: {message}")
        return None
    return parsed_data

def ip_str_to_int(ip_str: str) -> int:
    """Converts an IPv4 string to its integer representation."""
    try:
        return int(ipaddress.ip_address(ip_str))
    except ValueError:
        logger.error(f"Invalid IP string for conversion to int: {ip_str}")
        return 0

def ip_int_to_str(ip_int: int) -> str:
    """Converts an integer representation of an IPv4 address to string."""
    try:
        return str(ipaddress.ip_address(ip_int))
    except ValueError:
        logger.error(f"Invalid IP integer for conversion to str: {ip_int}")
        return "0.0.0.0"
