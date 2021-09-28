import os
import secrets
from typing import Any, List, Dict, Tuple, Callable, Union

from turbo_flask import Turbo
from flask import Flask, Blueprint, render_template, session, g


from .domain import Domain
from ...helpers.logger import logger
from ...helpers.cells import TurboCell, ViewCell
from ...tools.stdkit import format_error_message
from ...helpers.constants import HTTP_METHODS


class Omen(Domain):
    """Omen class inherits Domain superclass.
    
    Implements Flask App operating layer."""
    @logger.catch
    def __init__(
        self, 
        config: dict = None,
        cli_cmds: List[Callable] = None,
        shell_processors: List[Callable] = None,
        is_ctx_processor_enabled: bool = False,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        try:
            self.project_version = config["PROJECT_VERSION"]
        except KeyError:
            logger.warning("Project version hasn't been set in app config.")
            self.project_version = "not set"

        try:
            instance_path = config["INSTANCE_PATH"]
            template_folder = config["TEMPLATE_FOLDER"] 
            static_folder = config["STATIC_FOLDER"]
        except KeyError:
            error_message = format_error_message(
                "You must specify all of next parameters for app in config: INSTANCE_PATH, TEMPLATE_FOLDER, STATIC_FOLDER."
            )
            raise KeyError(error_message)

        self.app = Flask(
            __name__, 
            instance_path=instance_path, 
            template_folder=template_folder, 
            static_folder=static_folder
        )

        if config is not None:
            self.app.config.from_mapping(config)

        # Generate random hex token for App's secret key, if noone given in config.
        if self.app.config["SECRET_KEY"] is None:
            self.app.config["SECRET_KEY"] = secrets.token_hex(16)

        self.is_ctx_processor_enabled = is_ctx_processor_enabled
        self.turbo = Turbo(self.app)
        if cli_cmds:
            self._register_cli_cmds(cli_cmds)
        if shell_processors:
            self._register_shell_processors(shell_processors)
        self._init_app_daemons()

    def get_app(self) -> Flask:
        """Return native app."""
        return self.app

    def get_version(self):
        """Return project's version."""
        return self.project_version

    @logger.catch
    def register_view(self, view_cell: ViewCell) -> None:
        """Register given view cell for the app."""
        # Check if view has kwargs to avoid sending empty dict.
        # Use cell's name as view's endpoint.
        if view_cell.view_kwargs:
            view = view_cell.view_class.as_view(view_cell.name, **view_cell.view_kwargs)
        else:
            view = view_cell.view_class.as_view(view_cell.name)
        self.app.add_url_rule(view_cell.route, view_func=view, methods=HTTP_METHODS)

    def _register_cli_cmds(self, cmds: List[Callable]) -> None:
        """Register cli cmds for the app."""
        for cmd in cmds:
            self.app.cli.add_command(cmd)

    def _register_shell_processors(self, shell_processors: List[Callable]) -> None:
        """Register shell processors for the app."""
        for processor in shell_processors:
            self.app.shell_context_processor(processor)

    def _init_app_daemons(self) -> None:
        """Binds various background processes to the app."""
        flask_app = self.get_app()

        if self.is_ctx_processor_enabled:
            @logger.catch
            @flask_app.context_processor
            def invoke_ctx_processor_operations():
                ctx_data = self._invoke_ctx_processor_operations()
                if ctx_data is None:
                    return {}
                else:
                    return ctx_data

        @logger.catch
        @flask_app.before_request
        def invoke_each_request_operations():
            self._invoke_each_request_operations()

        @logger.catch
        @flask_app.before_first_request
        def invoke_first_request_operations():
            self._invoke_first_request_operations()

    def _invoke_ctx_processor_operations(self) -> dict:
        """Invoke context processor operations and return dict of their results.

        Proxy function, can be extended in children with functions to call without changing `_init_app_daemons` function."""
        pass

    def _invoke_each_request_operations(self) -> None:
        """Invoke before each request operations.
        
        Proxy function, can be extended in children with functions to call without changing `_init_app_daemons` function."""
        pass

    def _invoke_first_request_operations(self) -> None:
        """Invoke before first request operations.
        
        Proxy function, can be extended in children with functions to call without changing `_init_app_daemons` function."""
        pass