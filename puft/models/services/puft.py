import os
import secrets
from typing import Callable

from flask_cors import CORS
from turbo_flask import Turbo
from flask_session import Session
from puft.constants.hints import CLIModeEnumUnion
from warepy import logger, format_message, get_or_error
from flask import Flask, Blueprint, render_template, session, g
from warepy import logger

from .service import Service
from ...constants.enums import TurboActionEnum
from ...constants.hints import CLIModeEnumUnion
from ..domains.cells import ViewCell
from ...constants.enums import CLIRunEnum, TurboActionEnum
from ...constants.lists import HTTP_METHOD_ENUM_VALUES


class Puft(Service):
    """Operates over Puft processes.
    
    Should be inherited by project's AppService."""
    def __init__(
        self, 
        config: dict,
        mode_enum: CLIModeEnumUnion,
        host: str,
        port: int,
        cli_cmds: list[Callable] = None,
        shell_processors: list[Callable] = None,
        ctx_processor_enabled: bool = False,
    ) -> None:
        super().__init__(config)
        self.mode_enum = mode_enum
        self.host = host
        self.port = port
        self.flask_in_debug = self._choose_debug_flag(mode_enum)
        self.native_app = self._spawn_native_app(config)
        self.native_app.config.from_mapping(config)
        self._enable_cors(config)
        self._enable_testing_config(config)
        self._add_random_hex_token_to_config()
        self._resolve_ctx_processor_actions(ctx_processor_enabled)
        # Initialize turbo.js.
        # src: https://blog.miguelgrinberg.com/post/dynamically-update-your-flask-web-pages-using-turbo-flask
        self.turbo = Turbo(self.native_app)
        if cli_cmds:
            self._register_cli_cmds(cli_cmds)
        if shell_processors:
            self._register_shell_processors(shell_processors)
        self._init_app_daemons()
        # Initialize flask-session after all settings are applied.
        self.flask_session = Session(self.native_app)
        self._flush_redis_session_db()

    def _flush_redis_session_db(self) -> None:
        # Flush redis session db if mode is not `prod`. 
        if self.mode_enum is not CLIRunEnum.PROD: 
            if self.native_app.config.get("SESSION_TYPE", None):
                if self.native_app.config["SESSION_TYPE"] == "redis":
                    logger.info("Flush redis db because of non-production run.")
                    self.native_app.session_interface.redis.flushdb()
            else:
                # Apply default null interface, basically do nothing.
                pass
            
    def _resolve_ctx_processor_actions(self, ctx_processor_enabled: bool) -> None:
        self.ctx_processor_enabled = ctx_processor_enabled
        if self.ctx_processor_enabled:
            self.ctx_data = {}  # Live context data continiously pushed to app template context.
    
    def _add_random_hex_token_to_config(self) -> None:
        # Generate random hex token for App's secret key, if not given in config.
        if self.native_app.config["SECRET_KEY"] is None:
            self.native_app.config["SECRET_KEY"] = secrets.token_hex(16)
            
    def _enable_testing_config(self, config: dict) -> None:
        # Enable testing if appropriate mode has been set. Do not rely on enum if given config explicitly sets TESTING.
        if config.get("TESTING", None) is None:
            if self.mode_enum is CLIRunEnum.TEST:
                self.native_app.config["TESTING"] = True
            else:
                self.native_app.config["TESTING"] = False
        else:
            self.native_app.config["TESTING"] = config["TESTING"]
    
    def _enable_cors(self, config: dict) -> None:
        # Enable CORS for the app's resources.
        is_cors_enabled = config.get("IS_CORS_ENABLED", None)
        if is_cors_enabled:
            CORS(self.native_app)

    def _choose_debug_flag(self, mode_enum: CLIModeEnumUnion) -> bool:
        if mode_enum.value in ("dev", "test"): 
            return True
        else:
            return False

    def _spawn_native_app(self, config: dict) -> Flask:
        self.instance_path = self.config.get("INSTANCE_PATH", None)
        self.template_folder = self.config.get("TEMPLATE_FOLDER", None) 
        self.static_folder = self.config.get("STATIC_FOLDER", None)
        return Flask(
            __name__, 
            instance_path=self.instance_path, 
            template_folder=self.template_folder, 
            static_folder=self.static_folder
        )

    @logger.catch
    def get_native_app(self) -> Flask:
        """Return native app."""
        return self.native_app

    @logger.catch
    def get_instance_path(self) -> str:
        """Return app's instance path."""
        return self.native_app.instance_path

    @logger.catch
    def run(self) -> None:
        """Run Flask app."""
        self.native_app.run(
            host=self.host, port=self.port, debug=self.flask_in_debug
        )

    @logger.catch
    def register_view(self, view_cell: ViewCell) -> None:
        """Register given view cell for the app."""
        # Check if view has kwargs to avoid sending empty dict.
        # Use cell's name as view's endpoint.
        view = view_cell.view_class.as_view(view_cell.name)
        self.native_app.add_url_rule(view_cell.route, view_func=view, methods=HTTP_METHOD_ENUM_VALUES)

    @logger.catch
    def push_turbo(self, action: TurboActionEnum, target: str, template_path: str, ctx_data: dict = {}) -> None:
        """Push turbo action to target with rendered from path template contextualized with given data.
        
        Args:
            action: Turbo-Flask action to perform.
            target: Id of HTML element to push action to.
            template_path: Path to template to render.
            ctx_data (optional): Context data to push to rendered template. Defaults to empty dict.
        """
        with self.native_app.app_context():
            action = action.value
            target = target
            template_path = template_path
            ctx_data = ctx_data
            exec(f"self.turbo.push(self.turbo.{action}(render_template('{template_path}', **{ctx_data}), '{target}'))")

    def postbuild(self) -> None:
        """Abstract method to perform post-injection operation related to app. 
        
        Called by Assembler.

        WARNING: This method not working as intended now (runs not actually after app starting), so better to not use it temporary.
        
        Raise:
            NotImplementedError: If not re-implemented in children."""
        raise NotImplementedError("Method `postbuild` hasn't been reimplemented.")

    @logger.catch
    def _register_cli_cmds(self, cmds: list[Callable]) -> None:
        """Register cli cmds for the app."""
        for cmd in cmds:
            self.native_app.cli.add_command(cmd)

    @logger.catch
    def _register_shell_processors(self, shell_processors: list[Callable]) -> None:
        """Register shell processors for the app."""
        for processor in shell_processors:
            self.native_app.shell_context_processor(processor)

    @logger.catch
    def _init_app_daemons(self) -> None:
        """Binds various background processes to the app."""
        flask_app = self.get_native_app()

        if self.ctx_processor_enabled:
            @logger.catch
            @flask_app.context_processor
            def invoke_ctx_processor_operations():
                """Return continiously self live context data to app template processor.
                
                It might be useful in chain with turbo.js, when you push template changes
                and thus call flask context processor which in turn calls this return to template context."""
                return self.ctx_data

        @logger.catch
        @flask_app.before_request
        def invoke_each_request_operations():
            self._invoke_each_request_operations()

        @logger.catch
        @flask_app.before_first_request
        def invoke_first_request_operations():
            self._invoke_first_request_operations()

    def _invoke_each_request_operations(self) -> None:
        """Invoke before each request operations.
        
        Proxy function, can be extended in children with functions to call without changing `_init_app_daemons` function."""
        pass

    def _invoke_first_request_operations(self) -> None:
        """Invoke before first request operations.
        
        Proxy function, can be extended in children with functions to call without changing `_init_app_daemons` function."""
        pass