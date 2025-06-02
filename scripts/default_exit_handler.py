from typing import Dict, Any


class ExitHandlerScript:
    def __init__(self, api):
        self.api = api
        self.api.log_info("ExitHandlerScript initialized.")

    def load(self):
        """Subscribe to the CLIENT_SHUTDOWN_FINAL event."""
        self.api.subscribe_to_event(
            "CLIENT_SHUTDOWN_FINAL", self.handle_client_shutdown
        )
        self.api.log_info("Subscribed to CLIENT_SHUTDOWN_FINAL event.")

    def handle_client_shutdown(self, event_data: Dict[str, Any]):
        """Handle the client shutdown event by displaying a full-screen exit message."""
        try:
            width = 80  # Default width
            height = 24  # Default height
            border_char = "*"
            title = "PyRC - Python Terminal IRC Client"
            repo_url = "https://github.com/edgeof8/PyRC"

            lines = []
            lines.append(border_char * width)  # Top border

            # Centered Title
            title_padding_total = width - 2 - len(title)
            title_pad_left = title_padding_total // 2
            title_pad_right = title_padding_total - title_pad_left
            lines.append(
                f"{border_char}{' ' * title_pad_left}{title}{' ' * title_pad_right}{border_char}"
            )

            lines.append(
                f"{border_char}{' ' * (width - 2)}{border_char}"
            )  # Empty line with border

            content_messages = [
                "Thank you for using PyRC!",
                "We hope this terminal-based IRC client served you well.",
                "",
                "For more information, updates, or to contribute, please visit:",
                repo_url,
                "",
                "PyRC - Happy Chatting!",
                "Exiting application now...",
            ]

            content_width = (
                width - 4
            )  # Allow for border and one space padding on each side

            for msg in content_messages:
                if not msg:  # Handle empty lines for spacing
                    lines.append(f"{border_char}{' ' * (width - 2)}{border_char}")
                    continue

                # Simple word wrapping for content messages
                words = msg.split(" ")
                current_line_content = ""
                for word in words:
                    if not current_line_content:
                        current_line_content = word
                    elif len(current_line_content) + 1 + len(word) <= content_width:
                        current_line_content += " " + word
                    else:
                        # Print current line and start new one
                        pad_total = content_width - len(current_line_content)
                        pad_left = pad_total // 2
                        pad_right = pad_total - pad_left
                        lines.append(
                            f"{border_char} {' ' * pad_left}{current_line_content}{' ' * pad_right} {border_char}"
                        )
                        current_line_content = word

                # Print any remaining part of the message
                if current_line_content:
                    pad_total = content_width - len(current_line_content)
                    pad_left = pad_total // 2
                    pad_right = pad_total - pad_left
                    lines.append(
                        f"{border_char} {' ' * pad_left}{current_line_content}{' ' * pad_right} {border_char}"
                    )

            # Fill remaining lines to reach height
            # Subtract 1 for the bottom border that will be added
            while len(lines) < height - 1:
                lines.append(f"{border_char}{' ' * (width - 2)}{border_char}")

            lines.append(border_char * width)  # Bottom border

            # Print all lines
            for line in lines:
                print(line)

        except Exception as e:
            self.api.log_error(f"Error in exit handler: {e}")


def get_script_instance(api):
    """Factory function to create and return a script instance."""
    return ExitHandlerScript(api)
