

# START OF MODIFIED FILE: scripts/test_script.py
# scripts/test_script.py
# Ensure it's in a 'scripts' subdirectory next to pyrc.py


class TestScript:
    def __init__(
        self, api_handler
    ):  # Changed 'api' to 'api_handler' to match ScriptManager
        self.api = api_handler  # Store the API handler
        self.script_name = self.__class__.__module__  # Or "test_script"

    def load(self):
        self.api.log_info("TestScript loading...")
        self.api.register_command(
            command_name="testscript",
            handler_function=self.handle_test_command,
            help_info="Usage: /testscript [args] - A simple test command from a script.", # CHANGED to help_info
            aliases=["ts"],
        )
        self.api.log_info("TestScript loaded and command registered.")

    def handle_test_command(self, args_str: str, event_data: dict):
        # event_data contains keys like 'client_nick', 'active_context_name', 'raw_line', 'script_name'
        client_nick = self.api.get_client_nick()  # Or event_data['client_nick']
        script_name_from_event = event_data.get("script_name", "UnknownScriptViaEvent")

        message = f"TestScript (from {script_name_from_event}) executed by {client_nick}! Args: '{args_str}'"

        # Use a specific context or the active one
        active_context = self.api.get_current_context_name() or "Status"
        self.api.add_message_to_context(active_context, message, "system")

        self.api.send_raw(f"PING :testscript_was_here_from_{script_name_from_event}")
        self.api.log_info(f"Test command executed with args: {args_str}")


# Entry point for ScriptManager
def get_script_instance(api_handler):  # Changed 'api' to 'api_handler'
    return TestScript(api_handler)
# END OF MODIFIED FILE: scripts/test_script.py
