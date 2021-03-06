import os
import sys
import code
import secrets
from typing import Callable, Type

from flask_cors import CORS
from turbo_flask import Turbo
from flask_session import Session
from flask.testing import FlaskClient
from puft.core import validation
from puft.tools.log import log
from flask import Flask
from flask import cli as flask_cli
from flask.ctx import AppContext, RequestContext
from warepy import get_enum_values
from puft.tools.log import log

from puft.core.sv.sv import Sv
from puft.tools.hints import CLIModeEnumUnion
from puft.core.view.view_ie import ViewIe
from puft.core.cli.cli_run_enum import CLIRunEnum
from .http_method_enum import HTTPMethodEnum
from .turbo_action_enum import TurboActionEnum


class Puft(Sv):
    """Core app's class.
    """
    def __init__(
            self, 
            config: dict,
            mode_enum: CLIModeEnumUnion,
            host: str,
            port: int,
            ctx_processor_func: Callable | None = None,
            each_request_func: Callable | None = None,
            first_request_func: Callable | None = None) -> None:
        # Templates by default searched within src/app, which allows to
        # integrate them directly to their logical component's folders
        self.DEFAULT_TEMPLATE_PATH = os.path.join(
            config['root_path'], 'src/app')
        self.DEFAULT_STATIC_PATH = os.path.join(
            config['root_path'], 'src/assets')
        self.DEFAULT_INSTANCE_PATH = os.path.join(config['root_path'], 'var')

        # Convert all keys from given config to upper case
        self.config = self._make_upper_keys(config)
        self._assign_defaults_to_config(self.config)
        self._validate_config(self.config)

        # Flag for wildcard builtin error handler. Read by assembler in order
        # to register handler on build errors stage.
        self.wildcard_builtin_error_handler_enabled: bool = self.config.get(
            'wildcard_builtin_error_handler_enabled', True)
        validation.validate(self.wildcard_builtin_error_handler_enabled, bool)
        if self.wildcard_builtin_error_handler_enabled:
            log.info('Wildcard builtin error handler enabled')

        super().__init__(self.config)
        self.mode_enum = mode_enum
        self.host = host
        self.port = port
        self.native_app = self._spawn_native_app(self.config)
        self.native_app.config.from_mapping(self.config)
        self._enable_cors(self.config)
        self._enable_testing_config(self.config)
        self._add_random_hex_token_to_config()
        # Initialize turbo.js
        # https://blog.miguelgrinberg.com/post/dynamically-update-your-flask-web-pages-using-turbo-flask
        self.turbo = Turbo(self.native_app)
        # Initialize flask-session after all settings are applied
        self.flask_session = Session(self.native_app)
        self._flush_redis_session_db()

        self._init_app_daemons(
            ctx_processor_func=ctx_processor_func,
            each_request_func=each_request_func,
            first_request_func=first_request_func
        )

    def test_client(self) -> FlaskClient:
        return self.native_app.test_client()

    def _assign_defaults_to_config(self, config: dict) -> None:
        if 'TEMPLATE_PATH' not in config:
            config['TEMPLATE_PATH'] = self.DEFAULT_TEMPLATE_PATH
        if 'STATIC_PATH' not in config:
            config['STATIC_PATH'] = self.DEFAULT_STATIC_PATH
        if 'INSTANCE_PATH' not in config:
            config['INSTANCE_PATH'] = self.DEFAULT_INSTANCE_PATH

    def _validate_config(self, config: dict) -> None:
        """Check if all keys in the config are correct."""
        # TODO
        pass

    def _make_upper_keys(self, mapping: dict) -> dict:
        rmap = {}
        for k, v in mapping.items():
            rmap[k.upper()] = v
        return rmap
    
    def _enable_cors(self, config: dict) -> None:
        # Enable CORS for the app's resources.
        is_cors_enabled = config.get("IS_CORS_ENABLED", None)
        if is_cors_enabled:
            CORS(self.native_app)

    def _flush_redis_session_db(self) -> None:
        # Flush redis session db if mode is not `prod`. 
        if self.mode_enum is not CLIRunEnum.PROD: 
            if self.native_app.config.get("SESSION_TYPE", None):
                if self.native_app.config["SESSION_TYPE"] == "redis":
                    log.info(
                        "Flush session redis Db because"
                        " of non-production run.")
                    session_interface = self.native_app.session_interface
                    redis = session_interface.redis  # type: ignore
                    redis.flushdb()
            else:
                # Apply default null interface, basically do nothing.
                pass
    
    def _add_random_hex_token_to_config(self) -> None:
        # Generate random hex token for App's secret key, if not given in
        # config.
        if self.native_app.config["SECRET_KEY"] is None:
            self.native_app.config["SECRET_KEY"] = secrets.token_hex(16)
            
    def _enable_testing_config(self, config: dict) -> None:
        # Enable testing if appropriate mode has been set. Do not rely on enum
        # if given config explicitly sets TESTING.
        if config.get("TESTING", None) is None:
            if self.mode_enum is CLIRunEnum.TEST:
                self.native_app.config["TESTING"] = True
            else:
                self.native_app.config["TESTING"] = False
        else:
            self.native_app.config["TESTING"] = config["TESTING"]

    def _spawn_native_app(self, config: dict) -> Flask:
        self.instance_path = self.config.get("INSTANCE_PATH")
        self.template_folder = self.config.get("TEMPLATE_PATH") 
        self.static_folder = self.config.get("STATIC_PATH")

        # Set Flask environs according to given mode.
        # Setting exactly through environs instead of config recommended by
        # Flask creators.
        # https://flask.palletsprojects.com/en/2.0.x/config/#:~:text=Using%20the%20environment,a%20previous%20value.
        if self.mode_enum not in [CLIRunEnum.DEV, CLIRunEnum.TEST]:
            os.environ["FLASK_ENV"] = "production"
        else:
            os.environ["FLASK_ENV"] = "development"

        return Flask(
            __name__, 
            instance_path=self.instance_path, 
            template_folder=self.template_folder, 
            static_folder=self.static_folder
        )

    def get_secret_key(self) -> str:
        """Return secret key defined in App's config."""
        return self.native_app.config["SECRET_KEY"]

    def get_url(self) -> str:
        """Return app's url.

        Hostname may be e.g. `http://127.0.0.1:5000/`.

        Warning:
            Has url resolving issues described in issue #6.
        """
        return "http://" + self.host + ":" + str(self.port) + "/"

    def get_native_app(self) -> Flask:
        """Return native app."""
        return self.native_app

    def get_instance_path(self) -> str:
        """Return app's instance path."""
        return self.native_app.instance_path

    def run(self) -> None:
        """Run Flask app."""
        self.native_app.run(
            host=self.host, port=self.port)

    def app_context(self) -> AppContext:
        return self.native_app.app_context()

    def test_request_context(self) -> RequestContext:
        return self.native_app.test_request_context()

    def register_view(self, view_ie: ViewIe) -> None:
        """Register given view cell for the app."""
        # Check if view has kwargs to avoid sending empty dict.
        # Use cell's name as view's endpoint.
        if view_ie.endpoint:
            endpoint = view_ie.endpoint
        else:
            endpoint = view_ie.get_transformed_route()

        view = view_ie.view_class.as_view(endpoint)
        self.native_app.add_url_rule(
            view_ie.route, view_func=view,
            methods=get_enum_values(HTTPMethodEnum))

    def register_error(
            self,
            error_class: type[Exception],
            handler_function: Callable) -> None:
        self.native_app.register_error_handler(error_class, handler_function)

    def push_turbo(self, action: TurboActionEnum, target: str, template_path: str, ctx_data: dict = {}) -> None:
        """Push turbo action to target with rendered from path template
        contextualized with given data.
        
        Args:
            action:
                Turbo-Flask action to perform.
            target:
                Id of HTML element to push action to.
            template_path:
                Path to template to render.
            ctx_data (optional):
                Context data to push to rendered template.
                Defaults to empty dict.
        """
        with self.native_app.app_context():
            action = action.value
            target = target
            template_path = template_path
            ctx_data = ctx_data
            exec(
                f"self.turbo.push(self.turbo.{action}"
                "(render_template("
                f"'{template_path}', **{ctx_data}), '{target}'))")

    def postbuild(self) -> None:
        """Abstract method to perform post-injection operation related to app. 
        
        Called by Assembler.

        WARNING:
            This method not working as intended now (runs not actually after
            app starting), so better to not use it temporary.
        
        Raise:
            NotImplementedError:
                If not re-implemented in children.
        """
        raise NotImplementedError(
            "Method `postbuild` hasn't been reimplemented.")

    def register_cli_cmd(self, *cmds: Callable) -> None:
        """Register cli cmds for the app."""
        # TODO: Implement.
        raise NotImplementedError("CLI cmds support in development.")
        # for cmd in cmds:
        #     self.native_app.cli.add_command(cmd)

    def register_shell_processor(self, *shell_processors: Callable) -> None:
        """Register shell processors for the app."""
        for processor in shell_processors:
            self.native_app.shell_context_processor(processor)

    def run_shell(self) -> None:
        """Adapted version of ``Flask.cli.shell_command`` by Pallets.

        Run an interactive Python shell in the context of a given
        Flask application.  The application will populate the default
        namespace of this shell according to its configuration.

        This is useful for executing small snippets of management code
        without having to manually configure the application.
        """
        banner = (
            f"Python {sys.version} on {sys.platform}\n"
            f"App: {self.native_app.import_name} [{self.native_app.env}]\n"
            f"Instance: {self.native_app.instance_path}"
        )
        ctx: dict = {}

        # Support the regular Python interpreter startup script if someone
        # is using it.
        startup = os.environ.get("PYTHONSTARTUP")
        if startup and os.path.isfile(startup):
            with open(startup) as f:
                eval(compile(f.read(), startup, "exec"), ctx)

        ctx.update(self.native_app.make_shell_context())

        # Site, customize, or startup script can set a hook to call when
        # entering interactive mode. The default one sets up readline with
        # tab and history completion.
        interactive_hook = getattr(sys, "__interactivehook__", None)

        if interactive_hook is not None:
            try:
                import readline
                from rlcompleter import Completer
            except ImportError:
                pass
            else:
                # rlcompleter uses __main__.__dict__ by default, which is
                # flask.__main__. Use the shell context instead.
                readline.set_completer(Completer(ctx).complete)

            interactive_hook()

        code.interact(banner=banner, local=ctx)

    def _init_app_daemons(
            self, ctx_processor_func: Callable | None,
            each_request_func: Callable | None,
            first_request_func: Callable | None) -> None:
        """Binds various background processes to the app."""
        flask_app = self.get_native_app()

        if ctx_processor_func:
            @flask_app.context_processor
            def invoke_ctx_processor_func():
                return ctx_processor_func()

        if each_request_func:
            @flask_app.before_request
            def invoke_each_request_func():
                return each_request_func()

        if first_request_func:
            @flask_app.before_first_request
            def invoke_first_request_func():
                return first_request_func()
