import logging
import socket
import struct
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("pyrc.dcc.protocol")

def parse_ip_port_from_dcc_string(ip_int_str: str, port_str: str) -> Optional[Tuple[str, int]]:
    """
    Converts DCC SEND IP (integer string) and port string to a standard IP string and integer port.
    Returns None if parsing fails.
    """
    try:
        ip_int = int(ip_int_str)
        port = int(port_str)
        # Ensure port is valid
        if not (0 < port <= 65535):
            logger.warning(f"Invalid DCC port: {port_str}")
            return None
        # Convert packed integer IP to string IP
        ip_str = socket.inet_ntoa(struct.pack("!I", ip_int))
        return ip_str, port
    except (ValueError, struct.error, OverflowError) as e:
        logger.error(f"Error parsing DCC IP/Port '{ip_int_str}:{port_str}': {e}")
        return None

def format_ip_for_dcc_send(ip_str: str) -> Optional[int]:
    """
    Converts a standard IP string to the integer format required for DCC SEND.
    Returns None if formatting fails.
    """
    try:
        # Convert string IP to packed integer IP
        return struct.unpack("!I", socket.inet_aton(ip_str))[0]
    except (socket.error, struct.error) as e:
        logger.error(f"Error converting IP string '{ip_str}' for DCC SEND: {e}")
        return None

def parse_dcc_ctcp(ctcp_message: str) -> Optional[Dict[str, Any]]:
    """
    Parses a DCC CTCP message string.
    Example DCC SEND: "DCC SEND <filename> <ip_int> <port> <filesize>"
    Example DCC ACCEPT: "DCC ACCEPT <filename> <port> <position>"
    Returns a dictionary with parsed data or None if parsing fails.
    """
    parts = ctcp_message.strip().split()
    if not parts or parts[0] != "DCC" or len(parts) < 2:
        logger.debug(f"Not a valid DCC CTCP message or too short: {ctcp_message}")
        return None

    command = parts[1].upper()
    args = parts[2:]
    parsed_data: Dict[str, Any] = {"dcc_command": command}

    if command == "SEND":
        # DCC SEND <filename> <ip_int> <port> <filesize> [token]
        # Phase 1 focuses on the non-token version for active DCC.
        if len(args) < 4:
            logger.warning(f"DCC SEND message has too few arguments: {args}")
            return None

        # Filename might contain spaces, it's the first argument that isn't an IP.
        # A simple heuristic: if the second to last arg is a port and third to last is an IP.
        # This is tricky. Standard DCC SEND filename cannot contain spaces unless quoted.
        # For now, assume filename is args[0] and does not contain spaces.
        # If it can be quoted, parsing needs to be more robust.
        # Let's assume for now filename is the first argument and does not contain spaces.
        # A more robust parser would look for quotes or handle the last N args as fixed.

        filename = args[0] # This is a simplification. Real DCC filenames can be quoted.
        # For robust parsing, one might need to work backwards from filesize, port, ip.
        # Let's try to identify the numeric parts from the end.
        try:
            filesize_str = args[-1]
            port_str = args[-2]
            ip_int_str = args[-3]

            # Reconstruct filename if it was split due to spaces (simplistic approach)
            # This assumes filename is everything before ip_int_str
            num_fixed_args = 3 # ip, port, size
            if len(args) > num_fixed_args:
                 filename = " ".join(args[:-num_fixed_args])
            else: # Should not happen if len(args) >=4 and num_fixed_args = 3
                 logger.warning(f"Unexpected argument count for DCC SEND: {args}")
                 return None


            parsed_data["filename"] = filename.strip('"') # Remove quotes if present

            ip_port_tuple = parse_ip_port_from_dcc_string(ip_int_str, port_str)
            if not ip_port_tuple:
                return None
            parsed_data["ip_str"] = ip_port_tuple[0]
            parsed_data["port"] = ip_port_tuple[1]

            parsed_data["filesize"] = int(filesize_str)
            if parsed_data["filesize"] < 0:
                 logger.warning(f"Invalid DCC SEND filesize: {filesize_str}")
                 return None

            # Optional token for passive DCC (Phase 2)
            # if len(args) == 5:
            #    parsed_data["token"] = args[4]
            return parsed_data
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCC SEND arguments '{args}': {e}")
            return None

    elif command == "ACCEPT":
        # DCC ACCEPT <filename> <port> <position> [token]
        if len(args) < 3:
            logger.warning(f"DCC ACCEPT message has too few arguments: {args}")
            return None
        try:
            # Similar filename issue as SEND
            port_str = args[-2]
            position_str = args[-1]

            num_fixed_args = 2 # port, position
            if len(args) > num_fixed_args:
                 filename = " ".join(args[:-num_fixed_args])
            else:
                 logger.warning(f"Unexpected argument count for DCC ACCEPT: {args}")
                 return None

            parsed_data["filename"] = filename.strip('"')
            parsed_data["port"] = int(port_str)
            parsed_data["position"] = int(position_str)

            if not (0 < parsed_data["port"] <= 65535) or parsed_data["position"] < 0:
                logger.warning(f"Invalid DCC ACCEPT port/position: {args}")
                return None
            # Optional token
            # if len(args) == 4:
            #    parsed_data["token"] = args[3]
            return parsed_data
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCC ACCEPT arguments '{args}': {e}")
            return None

    # Add other DCC commands like RESUME, etc. later
    else:
        logger.debug(f"Unsupported DCC command: {command}")
        # Return a generic structure for unknown DCC commands if needed
        parsed_data["args"] = args
        return parsed_data

    return None # Should not be reached if all paths return

def format_dcc_send_ctcp(filename: str, ip_str: str, port: int, filesize: int) -> Optional[str]:
    """
    Formats a DCC SEND CTCP message string for active DCC.
    Returns None if formatting fails.
    """
    ip_int = format_ip_for_dcc_send(ip_str)
    if ip_int is None:
        return None

    if not (0 < port <= 65535) or filesize < 0:
        logger.error(f"Invalid port ({port}) or filesize ({filesize}) for DCC SEND.")
        return None

    # Quote filename if it contains spaces
    # Basic quoting: if space in filename, wrap with "
    # More robust quoting might be needed depending on IRC client compatibility.
    quoted_filename = f'"{filename}"' if " " in filename else filename

    return f"DCC SEND {quoted_filename} {ip_int} {port} {filesize}"

# Example Usage (for testing):
if __name__ == "__main__":
    # Test IP conversion
    print(f"IP 127.0.0.1 to int: {format_ip_for_dcc_send('127.0.0.1')}") # Expected: 2130706433
    print(f"IP 2130706433, Port 1234 from str: {parse_ip_port_from_dcc_string('2130706433', '1234')}")

    # Test DCC SEND parsing
    test_send_msg_1 = 'DCC SEND "my file name.txt" 2130706433 1234 10240'
    parsed_send_1 = parse_dcc_ctcp(test_send_msg_1)
    print(f"Parsed '{test_send_msg_1}': {parsed_send_1}")
    # Expected: {'dcc_command': 'SEND', 'filename': 'my file name.txt', 'ip_str': '127.0.0.1', 'port': 1234, 'filesize': 10240}

    test_send_msg_2 = "DCC SEND simplefile.zip 169090601 5000 204800" # 10.20.30.41
    parsed_send_2 = parse_dcc_ctcp(test_send_msg_2)
    print(f"Parsed '{test_send_msg_2}': {parsed_send_2}")

    # Test DCC SEND formatting
    formatted_send = format_dcc_send_ctcp("another file.dat", "192.168.1.10", 5678, 51200)
    print(f"Formatted DCC SEND: {formatted_send}")
    # Expected: DCC SEND "another file.dat" <ip_int_for_192.168.1.10> 5678 51200

    # Test DCC ACCEPT parsing
    test_accept_msg = 'DCC ACCEPT "my file name.txt" 1235 0'
    parsed_accept = parse_dcc_ctcp(test_accept_msg)
    print(f"Parsed '{test_accept_msg}': {parsed_accept}")
    # Expected: {'dcc_command': 'ACCEPT', 'filename': 'my file name.txt', 'port': 1235, 'position': 0}

    test_fail_send = "DCC SEND short"
    print(f"Parsed '{test_fail_send}': {parse_dcc_ctcp(test_fail_send)}")

    test_unknown_dcc = "DCC CHAT chat 2130706433 1236"
    print(f"Parsed '{test_unknown_dcc}': {parse_dcc_ctcp(test_unknown_dcc)}")
