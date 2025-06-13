import logging
import os
from typing import Optional, Any, Set, Dict, List
from dataclasses import asdict

from tirc_core.app_config import AppConfig
from tirc_core.config_defs import ServerConfig, DEFAULT_SSL_PORT, DEFAULT_PORT, DEFAULT_NICK # Corrected import
from tirc_core.state_manager import ConnectionInfo
from tirc_core.context_manager import ChannelJoinStatus

logger = logging.getLogger("tirc.initial_state_builder")

class InitialStateBuilder:
    def __init__(self, config: AppConfig, args: Any):
        self.config = config
        self.args = args

    def build(self) -> Optional[ConnectionInfo]:
        logger.debug("InitialStateBuilder: ENTERING build method.")
        active_config_for_initial_state: Optional[ServerConfig] = None
        default_server_for_nick: Optional[ServerConfig] = None

        if self.config.default_server_config_name:
            default_server_for_nick = self.config.all_server_configs.get(self.config.default_server_config_name)

        if self.args.server:
            port = self.args.port
            ssl = self.args.ssl
            if port is None:
                if ssl is None: ssl = False
                port = DEFAULT_SSL_PORT if ssl else DEFAULT_PORT
            elif ssl is None:
                ssl = (port == DEFAULT_SSL_PORT)
            cli_nick = self.args.nick or (default_server_for_nick.nick if default_server_for_nick else DEFAULT_NICK)
            active_config_for_initial_state = ServerConfig(
                server_id="CommandLine", address=self.args.server, port=port, ssl=ssl, nick=cli_nick,
                username=cli_nick, realname=cli_nick, channels=self.args.channel or [],
                server_password=self.args.password, nickserv_password=self.args.nickserv_password,
                sasl_username=None, sasl_password=None,
                verify_ssl_cert=self.args.verify_ssl_cert if self.args.verify_ssl_cert is not None else True,
                auto_connect=True, desired_caps=[]
            )
        elif self.config.default_server_config_name:
            active_config_for_initial_state = self.config.all_server_configs.get(self.config.default_server_config_name)

        if active_config_for_initial_state:
            server_config_dict = asdict(active_config_for_initial_state)
            # Map ServerConfig fields to ConnectionInfo fields, adjusting for 'address' -> 'server'
            conn_info_data = {k: v for k, v in server_config_dict.items() if k != 'address'}
            conn_info_data['server'] = server_config_dict['address']
            conn_info_data['initial_channels'] = server_config_dict.get('channels', [])

            if 'address' in conn_info_data: # Should be already handled by the line above
                conn_info_data['server'] = conn_info_data.pop('address')

            final_conn_info_data = {
                'server': conn_info_data.get('server'),
                'port': conn_info_data.get('port'),
                'ssl': conn_info_data.get('ssl'),
                'nick': conn_info_data.get('nick'),
                'username': conn_info_data.get('username', conn_info_data.get('nick')),
                'realname': conn_info_data.get('realname', conn_info_data.get('nick')),
                'server_password': conn_info_data.get('server_password'),
                'nickserv_password': conn_info_data.get('nickserv_password'),
                'sasl_username': conn_info_data.get('sasl_username'),
                'sasl_password': conn_info_data.get('sasl_password'),
                'verify_ssl_cert': conn_info_data.get('verify_ssl_cert', True),
                'auto_connect': conn_info_data.get('auto_connect', False),
                'initial_channels': conn_info_data.get('initial_channels', []),
                'desired_caps': conn_info_data.get('desired_caps', [])
            }
            conn_info_obj = ConnectionInfo(**final_conn_info_data) # type: ignore
            logger.debug("InitialStateBuilder: Successfully built ConnectionInfo object.")
            return conn_info_obj
        else:
            logger.info("InitialStateBuilder: No active server configuration found from CLI or default config.")
            return None
