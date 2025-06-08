import logging
import os
from typing import TYPE_CHECKING, Dict, Any

# --- PyRC ScriptBase ---
from pyrc_core.scripting.script_base import ScriptBase

if TYPE_CHECKING:
    from pyrc_core.scripting.script_api_handler import ScriptAPIHandler

# --- Google Cloud AI ---
try:
    from google.cloud import aiplatform_v1
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.struct_pb2 import Value

    GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") # Ensure this is set in your environment
    if GEMINI_API_KEY:
        # API key is now handled via environment variables or authentication
        GEMINI_AVAILABLE = True
    else:
        GEMINI_AVAILABLE = False
except ImportError:
    GEMINI_AVAILABLE = False

# --- Script Logger ---
script_logger = logging.getLogger("pyrc.scripts.api_responder_agent")

class ApiResponderAgent(ScriptBase):
    def __init__(self, api_handler: "ScriptAPIHandler"):
        super().__init__(api_handler)
        self.bot_nick: str = "PyRCBot" # Initial default, will be updated on CLIENT_READY
        self.model_name = "gemini-1.5-flash-latest" # Or your preferred Gemini model

        if not GEMINI_AVAILABLE:
            self.api.log_error("Gemini library or API key not available. Responder agent will be non-functional.")
        else:
            self.api.log_info(f"Gemini available. Using model: {self.model_name}")

    def load(self):
        self.api.log_info(f"ApiResponderAgent ({self.bot_nick}) loading...")
        # Subscribe to CLIENT_READY to get the final, resolved nickname
        self.api.subscribe_to_event("CLIENT_READY", self.handle_client_ready)
        # Also subscribe to NICK changes, in case the server forces a nick change later
        self.api.subscribe_to_event("NICK", self.handle_nick_change)
        self.api.subscribe_to_event("PRIVMSG", self.handle_privmsg)
        self.api.log_info(f"ApiResponderAgent subscribed to CLIENT_READY, NICK, and PRIVMSG. Listening for mentions.")

    def unload(self):
        self.api.log_info("ApiResponderAgent unloading...")

    def handle_client_ready(self, event_data: Dict[str, Any]):
        # Client is fully registered and ready; get the final nickname.
        conn_info = self.api.client_logic.state_manager.get_connection_info()
        if conn_info and conn_info.nick:
            self.bot_nick = conn_info.nick
            self.api.log_info(f"ApiResponderAgent adopted final nickname '{self.bot_nick}' after CLIENT_READY.")
        else:
            self.api.log_error("Cannot determine bot_nick: ConnectionInfo or nick not found after CLIENT_READY.")

    def handle_nick_change(self, event_data: Dict[str, Any]):
        # Update bot_nick if our own nickname changes
        old_nick = event_data.get("old_nick")
        new_nick = event_data.get("new_nick")
        # Ensure new_nick is a string before assignment
        if old_nick == self.bot_nick and isinstance(new_nick, str):
            self.bot_nick = new_nick
            self.api.log_info(f"ApiResponderAgent nickname changed from '{old_nick}' to '{new_nick}'.")
        elif new_nick is None:
            self.api.log_warning(f"Received NICK change event with None for new_nick. Old nick: {old_nick}.")

    def handle_privmsg(self, event_data: Dict[str, Any]):
        message: str = event_data.get("message", "")
        sender_nick: str = event_data.get("nick", "Unknown")
        target: str = event_data.get("target", "") # Channel or our nick (for PM)
        is_channel_msg: bool = event_data.get("is_channel_msg", False)

        if not self.bot_nick:
            script_logger.warning("Bot nickname is not set, cannot respond to messages.")
            return

        # Only respond to channel messages that mention the bot's nick at the start
        mention_pattern = f"{self.bot_nick.lower()}:"
        if is_channel_msg and message.lower().startswith(mention_pattern):
            query = message[len(mention_pattern):].strip()
            if query:
                script_logger.info(f"Bot mentioned in {target} by {sender_nick} with query: '{query}'")
                self.api.add_message_to_context(
                    target,
                    f"{sender_nick}: Thinking about '{query[:30]}...'...",
                    "system"
                )
                try:
                    if not GEMINI_AVAILABLE:
                        response_text = "Sorry, my AI brain (Gemini) is currently unavailable."
                    else:
                        client = aiplatform_v1.PredictionServiceClient()
                        endpoint = f"projects/{os.getenv('GCP_PROJECT_ID')}/locations/us-central1/endpoints/{self.model_name}"

                        # Format instances according to the expected type
                        instance = {"text": query}
                        value = Value()
                        value.string_value = query

                        response = client.predict(
                            endpoint=endpoint,
                            instances=[value],
                        )
                        predictions = [MessageToDict(pred) for pred in response.predictions]
                        response_text = predictions[0]["text"] if predictions else "I don't have a response for that right now."

                    # Split long responses
                    max_line_len = 400 # Typical IRC line limit is ~512, leave room for prefix
                    response_lines = [response_text[i:i+max_line_len] for i in range(0, len(response_text), max_line_len)]

                    for line in response_lines:
                        self.api.send_message(target, f"{sender_nick}: {line}")
                        script_logger.info(f"Sent response line to {target}: {line}")

                except Exception as e:
                    script_logger.error(f"Error calling Gemini API: {e}")
                    self.api.send_message(target, f"{sender_nick}: Sorry, I encountered an error trying to process your request.")
        elif not is_channel_msg and target.lower() == self.bot_nick.lower():
            # Respond to direct PMs
            query = message.strip()
            if query:
                script_logger.info(f"Bot received PM from {sender_nick} with query: '{query}'")
                self.api.add_message_to_context(
                    sender_nick, # Respond in the query window context
                    f"Thinking about your PM: '{query[:30]}...'...",
                    "system"
                )
                try:
                    if not GEMINI_AVAILABLE:
                        response_text = "Sorry, my AI brain (Gemini) is currently unavailable for PMs."
                    else:
                        client = aiplatform_v1.PredictionServiceClient()
                        endpoint = f"projects/{os.getenv('GCP_PROJECT_ID')}/locations/us-central1/endpoints/{self.model_name}"

                        # Format instances according to the expected type
                        instance = {"text": query}
                        value = Value()
                        value.string_value = query

                        response = client.predict(
                            endpoint=endpoint,
                            instances=[value],
                        )
                        predictions = [MessageToDict(pred) for pred in response.predictions]
                        response_text = predictions[0]["text"] if predictions else "I don't have a PM response for that."

                    max_line_len = 400
                    response_lines = [response_text[i:i+max_line_len] for i in range(0, len(response_text), max_line_len)]

                    for line in response_lines:
                        self.api.send_message(sender_nick, line) # Send PM back
                        script_logger.info(f"Sent PM response line to {sender_nick}: {line}")

                except Exception as e:
                    script_logger.error(f"Error calling Gemini API for PM: {e}")
                    self.api.send_message(sender_nick, "Sorry, I had trouble with your PM request.")
        sender_nick: str = event_data.get("nick", "Unknown")
        target: str = event_data.get("target", "") # Channel or our nick (for PM)
        is_channel_msg: bool = event_data.get("is_channel_msg", False)

        # Only respond to channel messages that mention the bot's nick at the start
        mention_pattern = f"{self.bot_nick.lower()}:"
        if is_channel_msg and message.lower().startswith(mention_pattern):
            query = message[len(mention_pattern):].strip()
            if query:
                script_logger.info(f"Bot mentioned in {target} by {sender_nick} with query: '{query}'")
                self.api.add_message_to_context(
                    target,
                    f"{sender_nick}: Thinking about '{query[:30]}...'...",
                    "system"
                )
                try:
                    if not GEMINI_AVAILABLE:
                        response_text = "Sorry, my AI brain (Gemini) is currently unavailable."
                    else:
                        client = aiplatform_v1.PredictionServiceClient()
                        endpoint = f"projects/{os.getenv('GCP_PROJECT_ID')}/locations/us-central1/endpoints/{self.model_name}"

                        # Format instances according to the expected type
                        instance = {"text": query}
                        value = Value()
                        value.string_value = query

                        response = client.predict(
                            endpoint=endpoint,
                            instances=[value],
                        )
                        predictions = [MessageToDict(pred) for pred in response.predictions]
                        response_text = predictions[0]["text"] if predictions else "I don't have a response for that right now."

                    # Split long responses
                    max_line_len = 400 # Typical IRC line limit is ~512, leave room for prefix
                    response_lines = [response_text[i:i+max_line_len] for i in range(0, len(response_text), max_line_len)]

                    for line in response_lines:
                        self.api.send_message(target, f"{sender_nick}: {line}")
                        script_logger.info(f"Sent response line to {target}: {line}")

                except Exception as e:
                    script_logger.error(f"Error calling Gemini API: {e}")
                    self.api.send_message(target, f"{sender_nick}: Sorry, I encountered an error trying to process your request.")
        elif not is_channel_msg and target.lower() == self.bot_nick.lower():
            # Respond to direct PMs
            query = message.strip()
            if query:
                script_logger.info(f"Bot received PM from {sender_nick} with query: '{query}'")
                self.api.add_message_to_context(
                    sender_nick, # Respond in the query window context
                    f"Thinking about your PM: '{query[:30]}...'...",
                    "system"
                )
                try:
                    if not GEMINI_AVAILABLE:
                        response_text = "Sorry, my AI brain (Gemini) is currently unavailable for PMs."
                    else:
                        client = aiplatform_v1.PredictionServiceClient()
                        endpoint = f"projects/{os.getenv('GCP_PROJECT_ID')}/locations/us-central1/endpoints/{self.model_name}"

                        # Format instances according to the expected type
                        instance = {"text": query}
                        value = Value()
                        value.string_value = query

                        response = client.predict(
                            endpoint=endpoint,
                            instances=[value],
                        )
                        predictions = [MessageToDict(pred) for pred in response.predictions]
                        response_text = predictions[0]["text"] if predictions else "I don't have a PM response for that."

                    max_line_len = 400
                    response_lines = [response_text[i:i+max_line_len] for i in range(0, len(response_text), max_line_len)]

                    for line in response_lines:
                        self.api.send_message(sender_nick, line) # Send PM back
                        script_logger.info(f"Sent PM response line to {sender_nick}: {line}")

                except Exception as e:
                    script_logger.error(f"Error calling Gemini API for PM: {e}")
                    self.api.send_message(sender_nick, "Sorry, I had trouble with your PM request.")

# Entry point for ScriptManager
def get_script_instance(api_handler: "ScriptAPIHandler"):
    return ApiResponderAgent(api_handler)
