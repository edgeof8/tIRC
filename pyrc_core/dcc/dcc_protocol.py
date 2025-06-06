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
    Example DCC SEND (Active): "DCC SEND <filename> <ip_int> <port> <filesize>"
    Example DCC SEND (Passive Offer): "DCC SEND <filename> <ip_int> 0 <filesize> <token>"
    Example DCC ACCEPT (Passive Response): "DCC ACCEPT <filename> <ip_int_receiver> <port_receiver> 0 <token>"
    Example DCC RESUME (Sender offers resume): "DCC RESUME <filename> <port_sender_listens_on> <resume_position>"
    Example DCC ACCEPT (Receiver accepts resume): "DCC ACCEPT <filename> <port_sender_listens_on> <resume_position>"
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
        # DCC SEND <filename> <ip_int> <port> <filesize> [token_if_port_is_0]
        if len(args) < 4: # Must have at least filename, ip, port, filesize
            logger.warning(f"DCC SEND message has too few arguments: {args}")
            return None

        try:
            # Determine if token is present based on arg count and if port is 0 (passive)
            # A passive send will have 5 args: filename ip 0 filesize token
            # An active send will have 4 args: filename ip port filesize

            is_potentially_passive = False
            temp_port_check = -1
            try:
                temp_port_check = int(args[-2 if len(args) == 4 else -3]) # port is 2nd from last (active) or 3rd (passive)
            except ValueError:
                logger.warning(f"Could not parse potential port for DCC SEND: {args}")
                return None

            if temp_port_check == 0 and len(args) == 5:
                is_potentially_passive = True
                token_str = args[-1]
                filesize_str = args[-2]
                port_str = args[-3] # Should be "0"
                ip_int_str = args[-4]
                num_fixed_args_at_end = 4 # ip, port, size, token
            elif len(args) >= 4 : # Active send or passive without token (less common)
                filesize_str = args[-1]
                port_str = args[-2]
                ip_int_str = args[-3]
                num_fixed_args_at_end = 3 # ip, port, size
            else: # Should have been caught by len(args) < 4
                logger.warning(f"DCC SEND logic error, unexpected arg count: {args}")
                return None

            filename = " ".join(args[:-num_fixed_args_at_end])
            parsed_data["filename"] = filename.strip('"')

            ip_port_tuple = parse_ip_port_from_dcc_string(ip_int_str, port_str)
            if not ip_port_tuple:
                return None # Error already logged by parse_ip_port_from_dcc_string

            parsed_data["ip_str"] = ip_port_tuple[0]
            parsed_data["port"] = ip_port_tuple[1] # This will be 0 for passive offers parsed here

            parsed_data["filesize"] = int(filesize_str)
            if parsed_data["filesize"] < 0:
                logger.warning(f"Invalid DCC SEND filesize: {filesize_str}")
                return None

            if is_potentially_passive and parsed_data["port"] == 0:
                parsed_data["token"] = token_str
                parsed_data["is_passive_offer"] = True
            elif parsed_data["port"] == 0: # Port 0 but not 5 args - ambiguous or malformed
                logger.warning(f"DCC SEND with port 0 but unexpected arg count for token: {args}")
                # We could treat it as active with port 0, but that's unusual.
                # For now, let's say it's not a valid passive offer if token is missing.
                parsed_data["is_passive_offer"] = False # Or return None

            return parsed_data
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCC SEND arguments '{args}': {e}", exc_info=True)
            return None

    elif command == "ACCEPT":
        # For Passive DCC flow: DCC ACCEPT <filename> <ip_int_receiver> <port_receiver> 0 <token>
        # For Resume (Active DCC): DCC ACCEPT <filename> <port_sender_listens_on_normally> <resume_position>
        # We need to distinguish. A key difference is the presence of an IP for passive.
        # Let's assume if 4 or 5 args, and 4th arg (position) is 0, it *could* be passive response.

        if len(args) < 3: # filename, port, position (for resume) OR filename, ip, port, position (for passive)
            logger.warning(f"DCC ACCEPT message has too few arguments: {args}")
            return None
        try:
            # Try to parse as Passive DCC ACCEPT first (filename ip port position token)
            if len(args) >= 4: # Potentially passive (filename, ip, port, position=0, [token])
                token_str = None
                if len(args) == 5:
                    token_str = args[-1]
                position_str = args[-2 if token_str else -1]
                port_str = args[-3 if token_str else -2]
                ip_int_str = args[-4 if token_str else -3]

                num_fixed_args_at_end = 3 if not token_str else 4
                filename = " ".join(args[:-num_fixed_args_at_end])

                parsed_data["filename"] = filename.strip('"')

                # Check if this looks like a passive accept (position is 0 and ip_int_str is parsable as IP)
                is_passive_accept = False
                temp_position_check = -1
                try: temp_position_check = int(position_str)
                except ValueError: pass

                ip_port_tuple = parse_ip_port_from_dcc_string(ip_int_str, port_str)

                if ip_port_tuple and temp_position_check == 0:
                    is_passive_accept = True
                    parsed_data["ip_str"] = ip_port_tuple[0] # Receiver's listening IP
                    parsed_data["port"] = ip_port_tuple[1]   # Receiver's listening port
                    parsed_data["position"] = 0
                    if token_str:
                        parsed_data["token"] = token_str
                    parsed_data["is_passive_accept"] = True
                    return parsed_data
                # If not a clear passive accept, fall through to try parsing as resume accept

            # Try to parse as Resume DCC ACCEPT (filename port position)
            if len(args) == 3: # filename, port, position (standard resume)
                position_str = args[-1]
                port_str = args[-2]
                filename = args[0].strip('"') # Simplification, assumes filename is first

                parsed_data["filename"] = filename
                parsed_data["port"] = int(port_str) # Port the original sender was listening on
                parsed_data["position"] = int(position_str)
                parsed_data["is_resume_accept"] = True

                if not (0 <= parsed_data["port"] <= 65535) or parsed_data["position"] < 0: # Port can be 0 if it was a passive offer being resumed? Unlikely.
                    logger.warning(f"Invalid DCC ACCEPT (resume) port/position: {args}")
                    return None
                return parsed_data

            logger.warning(f"Could not parse DCC ACCEPT arguments as passive or resume: {args}")
            return None

        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCC ACCEPT arguments '{args}': {e}", exc_info=True)
            return None

    elif command == "DCCCHECKSUM": # New command
        # DCC DCCCHECKSUM <filename> <algorithm> <checksum_value> <transfer_identifier>
        if len(args) < 4:
            logger.warning(f"DCCCHECKSUM message has too few arguments: {args}")
            return None
        try:
            # Filename can contain spaces, so it's everything before the last 3 args
            transfer_identifier = args[-1]
            checksum_value = args[-2]
            algorithm = args[-3]

            num_fixed_args_at_end = 3 # algorithm, checksum_value, transfer_identifier
            if len(args) > num_fixed_args_at_end:
                 filename = " ".join(args[:-num_fixed_args_at_end])
            else: # Should be at least 4 args, so filename must be args[0]
                 filename = args[0]


            parsed_data["filename"] = filename.strip('"')
            parsed_data["algorithm"] = algorithm.lower()
            parsed_data["checksum_value"] = checksum_value
            parsed_data["transfer_identifier"] = transfer_identifier
            return parsed_data
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCCCHECKSUM arguments '{args}': {e}", exc_info=True)
            return None

    elif command == "RESUME": # Sender offers to resume a send
        # DCC RESUME <filename> <port> <position>
        if len(args) < 3:
            logger.warning(f"DCC RESUME message has too few arguments: {args}")
            return None
        try:
            position_str = args[-1]
            port_str = args[-2]
            filename = " ".join(args[:-2]).strip('"')

            parsed_data["filename"] = filename
            parsed_data["port"] = int(port_str)
            parsed_data["position"] = int(position_str)

            if not (0 < parsed_data["port"] <= 65535) or parsed_data["position"] < 0:
                logger.warning(f"Invalid DCC RESUME port/position: {args}")
                return None
            return parsed_data
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing DCC RESUME arguments '{args}': {e}", exc_info=True)
            return None
    else:
        logger.debug(f"Unsupported DCC command: {command}")
        # Return a generic structure for unknown DCC commands if needed
        parsed_data["args"] = args
        return parsed_data

    return None # Should not be reached if all paths return

def format_dcc_send_ctcp(filename: str, ip_str: str, port: int, filesize: int, token: Optional[str] = None) -> Optional[str]:
    """
    Formats a DCC SEND CTCP message string.
    If port is 0 and token is provided, it's formatted for a passive DCC offer.
    Otherwise, it's for an active DCC offer.
    Returns None if formatting fails.
    """
    # For passive sends (port 0), ip_str can be "0" or a real IP.
    # format_ip_for_dcc_send should handle "0" as "0.0.0.0" -> 0.
    # If ip_str is "0", it will correctly convert to the integer 0.
    ip_int = format_ip_for_dcc_send(ip_str if ip_str != "0" else "0.0.0.0")
    if ip_int is None: # format_ip_for_dcc_send failed for a non-"0" IP
        logger.error(f"Failed to format IP '{ip_str}' for DCC SEND.")
        return None

    # Port 0 is valid for passive DCC. Otherwise, 1-65535.
    if not (0 <= port <= 65535) or filesize < 0:
        logger.error(f"Invalid port ({port}) or filesize ({filesize}) for DCC SEND.")
        return None
    if port != 0 and not (0 < port <= 65535): # Stricter check for non-passive
         logger.error(f"Invalid non-zero port ({port}) for active DCC SEND.")
         return None

    quoted_filename = f'"{filename}"' if " " in filename else filename

    if port == 0 and token: # Passive DCC SEND offer
        return f"DCC SEND {quoted_filename} {ip_int} 0 {filesize} {token}"
    elif port == 0 and not token: # Passive DCC offer requires a token by our convention
        logger.warning("Formatting passive DCC SEND (port 0) but no token provided. This might not be standard.")
        # Proceeding, but it's unusual. Some clients might send IP 0 Port 0 without token.
        return f"DCC SEND {quoted_filename} {ip_int} 0 {filesize}"
    else: # Active DCC SEND
        return f"DCC SEND {quoted_filename} {ip_int} {port} {filesize}"

def format_dcc_accept_ctcp(filename: str, ip_str: str, port: int, position: int, token: Optional[str] = None) -> Optional[str]:
    """
    Formats a DCC ACCEPT CTCP message string.
    Scenario 1 (Passive DCC Accept):
        Receiver accepts a passive DCC SEND offer.
        ip_str: Receiver's listening IP.
        port: Receiver's listening port.
        position: Typically 0 for passive accept.
        token: The token from the SEND offer.
    Scenario 2 (Resume Accept):
        Receiver accepts a DCC RESUME offer or proactively requests to resume a standard DCC SEND.
        ip_str: Often "0" or ignored by sender, as port and filename identify the transfer.
        port: Port the original sender is (or was) listening on for this file.
        position: Byte offset from which to resume.
        token: None for this scenario.
    Returns None if formatting fails.
    """
    ip_int = format_ip_for_dcc_send(ip_str if ip_str != "0" else "0.0.0.0")
    if ip_int is None:
        logger.error(f"Failed to format IP '{ip_str}' for DCC ACCEPT.")
        return None

    if not (0 <= port <= 65535) or position < 0:
        logger.error(f"Invalid port ({port}) or position ({position}) for DCC ACCEPT.")
        return None

    quoted_filename = f'"{filename}"' if " " in filename else filename

    if token: # Typically for passive DCC accept
        return f"DCC ACCEPT {quoted_filename} {ip_int} {port} {position} {token}"
    else: # Typically for resume of active DCC
        return f"DCC ACCEPT {quoted_filename} {port} {position}" # Old format for resume without IP

def format_dcc_checksum_ctcp(filename: str, algorithm: str, checksum: str, transfer_identifier: str) -> str:
    """Formats a DCCCHECKSUM CTCP message string."""
    quoted_filename = f'"{filename}"' if " " in filename else filename
    return f"DCC DCCCHECKSUM {quoted_filename} {algorithm.lower()} {checksum} {transfer_identifier}"

def format_dcc_resume_ctcp(filename: str, port: int, position: int) -> Optional[str]:
    """
    Formats a DCC RESUME CTCP message string (sender offers to resume).
    <filename>: The name of the file.
    <port>: The port the sender is now listening on for the resumed connection.
    <position>: The byte offset from which the transfer should continue.
    Returns None if formatting fails.
    """
    if not (0 < port <= 65535) or position < 0:
        logger.error(f"Invalid port ({port}) or position ({position}) for DCC RESUME.")
        return None

    quoted_filename = f'"{filename}"' if " " in filename else filename
    return f"DCC RESUME {quoted_filename} {port} {position}"

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

    # Test DCC ACCEPT parsing (Passive Response)
    test_accept_passive_msg = 'DCC ACCEPT "my file name.txt" 2130706433 1235 0 mytoken123'
    parsed_accept_passive = parse_dcc_ctcp(test_accept_passive_msg)
    print(f"Parsed PASSIVE ACCEPT '{test_accept_passive_msg}': {parsed_accept_passive}")
    # Expected: {'dcc_command': 'ACCEPT', 'filename': 'my file name.txt', 'ip_str': '127.0.0.1', 'port': 1235, 'position': 0, 'token': 'mytoken123', 'is_passive_accept': True}

    # Test DCC ACCEPT parsing (Resume)
    test_accept_resume_msg = 'DCC ACCEPT "another.zip" 5000 102400'
    parsed_accept_resume = parse_dcc_ctcp(test_accept_resume_msg)
    print(f"Parsed RESUME ACCEPT '{test_accept_resume_msg}': {parsed_accept_resume}")
    # Expected: {'dcc_command': 'ACCEPT', 'filename': 'another.zip', 'port': 5000, 'position': 102400, 'is_resume_accept': True}

    # Test DCC SEND Passive formatting
    formatted_send_passive = format_dcc_send_ctcp("passive file.dat", "10.0.0.5", 0, 60000, "passtoken789")
    print(f"Formatted PASSIVE DCC SEND: {formatted_send_passive}")
    # Expected: DCC SEND "passive file.dat" <ip_int_for_10.0.0.5> 0 60000 passtoken789

    # Test DCC ACCEPT Passive formatting
    formatted_accept_passive = format_dcc_accept_ctcp("passive file.dat", "192.168.5.50", 7000, 0, "passtoken789")
    print(f"Formatted PASSIVE DCC ACCEPT: {formatted_accept_passive}")
    # Expected: DCC ACCEPT "passive file.dat" <ip_int_for_192.168.5.50> 7000 0 passtoken789

    test_fail_send = "DCC SEND short"
    print(f"Parsed '{test_fail_send}': {parse_dcc_ctcp(test_fail_send)}")

    test_unknown_dcc = "DCC CHAT chat 2130706433 1236"
    print(f"Parsed '{test_unknown_dcc}': {parse_dcc_ctcp(test_unknown_dcc)}")

    # Test DCCCHECKSUM parsing and formatting
    formatted_checksum = format_dcc_checksum_ctcp("my movie.avi", "MD5", "a1b2c3d4e5f6", "transferXYZ")
    print(f"Formatted DCCCHECKSUM: {formatted_checksum}")
    # Expected: DCC DCCCHECKSUM "my movie.avi" md5 a1b2c3d4e5f6 transferXYZ
    parsed_checksum = parse_dcc_ctcp(formatted_checksum) # Use the main parser
    print(f"Parsed DCCCHECKSUM: {parsed_checksum}")
    # Expected: {'dcc_command': 'DCCCHECKSUM', 'filename': 'my movie.avi', 'algorithm': 'md5', 'checksum_value': 'a1b2c3d4e5f6', 'transfer_identifier': 'transferXYZ'}

    # Test DCC RESUME parsing and formatting
    formatted_resume = format_dcc_resume_ctcp("resume test.file", 6000, 12345)
    print(f"Formatted DCC RESUME: {formatted_resume}")
    # Expected: DCC RESUME "resume test.file" 6000 12345
    if formatted_resume:
        parsed_resume = parse_dcc_ctcp(formatted_resume)
        print(f"Parsed DCC RESUME: {parsed_resume}")
        # Expected: {'dcc_command': 'RESUME', 'filename': 'resume test.file', 'port': 6000, 'position': 12345}
