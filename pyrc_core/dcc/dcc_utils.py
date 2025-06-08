import logging
import socket
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("pyrc.dcc.utils")

def get_listening_socket(dcc_config: Dict[str, Any], dcc_event_logger: logging.Logger) -> Optional[Tuple[socket.socket, int]]:
    """Finds an available port in the configured range and returns a listening socket."""
    port_start = dcc_config.get("port_range_start", 1024)
    port_end = dcc_config.get("port_range_end", 65535)

    if port_start > port_end:
        dcc_event_logger.warning(f"Invalid port range: start ({port_start}) > end ({port_end}). Using default range 1024-65535.")
        port_start = 1024
        port_end = 65535

    ports_to_try = list(range(port_start, port_end + 1))
    dcc_event_logger.info(f"Attempting to find available DCC port in range {port_start}-{port_end}")

    for port in ports_to_try:
        s: Optional[socket.socket] = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("", port))  # Bind to all interfaces on the current port
            s.listen(1)  # Listen for one incoming connection for this transfer
            dcc_event_logger.info(f"Successfully bound DCC listening socket to port {port}.")
            return s, port
        except socket.error as e:
            if e.errno == 98:  # EADDRINUSE
                dcc_event_logger.debug(f"Port {port} already in use, trying next.")
            else:
                dcc_event_logger.warning(f"Could not bind to port {port}: {e}. Trying next.")
            if s:  # Ensure socket is closed if bind failed after creation
                s.close()
        except Exception as ex:
            dcc_event_logger.error(f"Unexpected error trying port {port}: {ex}")
            if s:
                s.close()

    # If we get here, all ports in the range failed
    dcc_event_logger.error(f"Could not find an available DCC listening port in range {port_start}-{port_end}.")
    # Note: client_logic.add_message cannot be called from here, as DCCManager will handle messages.
    return None

def get_local_ip_for_ctcp(dcc_config: Dict[str, Any], dcc_event_logger: logging.Logger) -> str:
    """Attempts to determine a suitable local IP address for CTCP messages."""
    configured_ip = dcc_config.get("advertised_ip")
    if configured_ip and isinstance(configured_ip, str) and configured_ip.strip():
        # Validate the configured IP format
        try:
            socket.inet_aton(configured_ip) # Basic validation
            dcc_event_logger.info(f"Using configured DCC advertised IP: {configured_ip}")
            return configured_ip
        except socket.error:
            dcc_event_logger.warning(f"Configured dcc_advertised_ip '{configured_ip}' is invalid. Falling back to auto-detection.")

    # Existing auto-detection logic:
    try:
        temp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        temp_s.settimeout(0.5)
        temp_s.connect(("8.8.8.8", 80))
        local_ip = temp_s.getsockname()[0]
        temp_s.close()
        dcc_event_logger.debug(f"Auto-detected DCC IP via external connect: {local_ip}")
        return local_ip
    except socket.error:
        dcc_event_logger.warning("Could not determine local IP for DCC CTCP using external connect. Trying hostname.")
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            dcc_event_logger.debug(f"Auto-detected DCC IP via gethostname: {local_ip}")
            return local_ip
        except socket.gaierror:
            dcc_event_logger.warning("Could not determine local IP via gethostname. Falling back to '127.0.0.1'.")
            return "127.0.0.1"
