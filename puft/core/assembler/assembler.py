from __future__ import annotations
import os
import sys
import importlib.util
from typing import Dict, TYPE_CHECKING, Any, TypeVar

from warepy import (
    join_paths, format_message, load_yaml, get_enum_values, Singleton
)
from flask_socketio import SocketIO
import pytest
from puft.core.cli.cli_db_enum import CLIDbEnum
from puft.core.cli.cli_error import CLIError
from puft.core.cli.cli_helper_enum import CLIHelperEnum

from puft.core.sock.socket import Socket
from puft.core.sv.sv import Sv
from puft.tools.hints import CLIModeEnumUnion
from puft.tools.log import log
from puft.core.app.app_mode_enum import AppModeEnum
from puft.core.cli.cli_run_enum import CLIRunEnum
from puft.core.error.error import Error
from puft.tools.error_handlers import handle_wildcard_builtin_error, handle_wildcard_error
from puft.core.ie.named_ie import NamedIe
from puft.core.ie.config_ie import ConfigIe
from puft.core.app.puft_sv_ie import PuftSvIe
from puft.core.db.db_sv_ie import DbSvIe
from puft.core.sock.sock_sv_ie import SocketSvIe
from puft.core.sv.sv_ie import SvIe
from puft.core.view.view_ie import ViewIe
from puft.core.emt.emt_ie import EmtIe
from puft.core.error.error_ie import ErrorIe

from puft.core.db.db import Db
from puft.core.app.puft import Puft
from puft.tools.hints import CLIModeEnumUnion
from .config_extension_enum import ConfigExtensionEnum

if TYPE_CHECKING:
    from .build import Build


class Assembler(Singleton):
    """Assembles all project instances and initializes it.

    Acts automatically and shouldn't be inherited directly by project in any
    form.

    TODO: Write all init args
    Args:
        extra_configs_by_name (optional):
            Configs to be appended to appropriate ones described in Build
            class. Defaults to None.
            Contain config name as key (which is compared to ConfigIe
            name field) and configuration mapping as value, e.g.:
    ```python
    extra_configs_by_name = {
        "app": {"TESTING": True},
        "db": {"db_uri": "sqlite3:///:memory:"}
    }
    ```
        root_dir (optional):
            Root dir to execute project from. Defaults to `os.getcwd()`.
            Required in cases of calling this function not from actual
            project root (e.g. from tests) to set root path explicitly.
    """
    DEFAULT_LOG_PARAMS = {
        "path": "./var/logs/system.log",
        "level": "DEBUG",
        "format":
            "{time:%Y.%m.%d at %H:%M:%S:%f%z} | {level} | {extra} >> {message}",
        "rotation": "10 MB",
        "serialize": False
    }

    def __init__(
            self, 
            mode_enum: CLIModeEnumUnion,
            mode_args: list[str] = [],
            source_filename: str = 'build',
            build: Build | None = None,
            host: str = 'localhost',
            port: int = 5000,
            root_dir: str = os.getcwd(),
            extra_configs_by_name: dict[str, Any] | None = None) -> None:
        # Define attributes for getter methods to be used at builder
        # Do not set extra_configs_by_name to None at initialization, because
        # `get()` method called from this dictionary
        self.extra_configs_by_name = {}
        self.root_dir = root_dir
        self.default_wildcard_error_handler_func = handle_wildcard_error
        self.socket_enabled: bool = False

        self.mode_enum: CLIModeEnumUnion = mode_enum
        self.mode_args: list[str] = mode_args

        # Load build from module
        if build:
            self.build = build
        else:
            self.build = self._load_target_build(source_filename)

        # Use build in further assignment
        self.sv_ies = self.build.sv_ies
        self.view_ies = self.build.view_ies
        self.error_ies: list[ErrorIe] = self.build.error_ies
        self.emt_ies = self.build.emt_ies
        self.shell_processors = self.build.shell_processors
        self.cli_cmds = self.build.cli_cmds
        self.ctx_processor_func = self.build.ctx_processor_func
        self.each_request_func = self.build.each_request_func
        self.first_request_func = self.build.first_request_func
        self.sock_ies = self.build.sock_ies
        self.default_sock_error_handler = self.build.default_sock_error_handler
        self._assign_config_ies(self.build.config_dir)
        # Traverse given configs and assign enabled builtin cells
        self._assign_builtin_sv_ies(mode_enum, host, port)
        # Namespace to hold all initialized services. Should be used only for
        # testing purposes, when direct import of services are unavailable
        self._custom_svs: dict[str, Any] = {}

        # Add extra configs
        if extra_configs_by_name:
            self.extra_configs_by_name = extra_configs_by_name

        self._register_self_singleton()
        self._build_all()

    def _register_self_singleton(self):
        """Register self instance to Singleton instance.
        
        This should be done at initialization to avoid built services Assembler
        initialization problem via `Assembler.instance()` call.
        """
        type(self.__class__).instances[self.__class__] = self

    def _load_target_build(self, source_filename: str) -> Build:
        """Load target module spec from location, where cli were called."""
        # Add root_dir to sys.path to avoid ModuleNotFoundError during lib
        # importing
        sys.path.append(self.root_dir)

        module_location = os.path.join(self.root_dir, source_filename + ".py")
        module_spec = importlib.util.spec_from_file_location(
            source_filename, module_location)
        if module_spec and module_spec.loader:
            main_module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(main_module)
            # TODO: Add validation of result build?
            return main_module.build
        else:
            raise NameError(
                format_message(
                    "Could not resolve module spec for location: {}.",
                    module_location))

    def get_puft(self) -> Puft:
        return self.puft

    def get_db(self) -> Db:
        return self.db

    def get_root_dir(self) -> str:
        return self.root_dir

    def get_mode_enum(self) -> CLIModeEnumUnion:
        return self.mode_enum

    def _assign_config_ies(self, config_dir: str) -> None:
        """Traverse through config files under given config_dir and create 
        ConfigIes from them.

        Name taken from filename of config and should be the same as specified 
        at config's target sv_ie.name.

        Names can contain additional extension like `name.prod.yaml` according
        to appropriate Puft modes. These configs launched per each mode. Config
        without this extra extension, considered `prod` moded.
        """
        self.config_ies: list[ConfigIe] = []

        config_path: str = join_paths(self.root_dir, config_dir)
        source_map_by_name: dict[str, dict[AppModeEnum, str]] = \
            self._find_config_files(config_path)

        for name, source_map in source_map_by_name.items():
            self.config_ies.append(ConfigIe(
                name=name,
                source_by_app_mode=source_map))

    def _find_config_files(
            self, config_path: str) -> dict[str, dict[AppModeEnum, str]]:
        """Accept path to config dir and return dict describing all paths to
        configs for all app modes per sv name.
        
        Return example:
        ```python
        {
            "custom_sv_name": {
                AppModeEnum.PROD: "./some/path",
                AppModeEnum.DEV: "./some/path",
                AppModeEnum.TEST: "./some/path"
            }
        }
        ```
        """
        source_map_by_name = {} 
        for filename in os.listdir(config_path):
            # Pick files only under config_dir.
            if os.path.isfile(join_paths(config_path, filename)):
                parts = filename.split(".")
                file_path = join_paths(config_path, filename)

                if len(parts) == 1:
                    # Skip files without extension.
                    continue
                # Check if file has supported extension.
                elif len(parts) == 2:
                    # Config name shouldn't contain dots and thus we can grab
                    # it right here.
                    config_name = parts[0]
                    if parts[1] in get_enum_values(ConfigExtensionEnum):
                        # Add file without app mode automatically to
                        # `prod`.
                        if config_name not in source_map_by_name:
                            source_map_by_name[config_name] = dict()
                        source_map_by_name[config_name][
                            AppModeEnum.PROD] = file_path
                    else:
                        # Skip files with unsupported extension.
                        continue
                elif len(parts) == 3:
                    # Config name shouldn't contain dots and thus we can grab
                    # it right here.
                    config_name = parts[0]
                    if parts[1] in get_enum_values(AppModeEnum) \
                            and parts[2] in get_enum_values(
                                ConfigExtensionEnum):
                        # File has both normal extension and defined
                        # app mode.
                        if config_name not in source_map_by_name:
                            source_map_by_name[config_name] = dict()
                        source_map_by_name[config_name][
                            AppModeEnum(parts[1])] = file_path
                    else:
                        # Unrecognized app mode or extension,
                        # maybe raise warning?
                        continue
                else:
                    # Skip files with names containing dots, e.g.
                    # "dummy.new.prod.yaml".
                    continue
        return source_map_by_name

    def _assign_builtin_sv_ies(
            self, mode_enum: CLIModeEnumUnion, host: str, port: int) -> None:
        """Assign builting sv cells if configuration file for its sv
        exists.
        """
        self.builtin_sv_ies: list[Any] = [PuftSvIe(
            name="puft",
            sv_class=Puft,
            mode_enum=mode_enum,
            host=host,
            port=port
        )]
        log_layers: list[str] = []

        # Enable only modules with specified configs.
        if self.config_ies:
            try:
                NamedIe.find_by_name("db", self.config_ies)
            except ValueError:
                pass
            else:
                self.builtin_sv_ies.append(DbSvIe(
                    name="db",
                    sv_class=Db
                ))
                log_layers.append('db')

            try:
                NamedIe.find_by_name('socket', self.config_ies)
            except ValueError:
                pass
            else:
                self.builtin_sv_ies.append(SocketSvIe(
                    name='socket',
                    sv_class=Socket))
                self.socket_enabled = True
                log_layers.append('socket')
            
            if log_layers:
                log.info(f'Enabled layers: {", ".join(log_layers)}')

    def run(self):
        if isinstance(self.mode_enum, CLIRunEnum):
            if self.mode_enum is CLIRunEnum.TEST:
                self._run_test()
            else:
                self._run_app()
        elif isinstance(self.mode_enum, CLIHelperEnum):
            if self.mode_enum is CLIHelperEnum.SHELL:
                self._run_shell()
            elif self.mode_enum is CLIHelperEnum.CMD: 
                # TODO: Custom cmds after assembler build operations.
                raise NotImplementedError
            elif self.mode_enum is CLIHelperEnum.DEPLOY:
                # TODO: Implement deploy operation.
                raise NotImplementedError
            else:
                raise TypeError
        elif isinstance(self.mode_enum, CLIDbEnum):
            with self.puft.app_context():
                if self.mode_enum is CLIDbEnum.INIT:
                    self.db.init_migration()
                elif self.mode_enum is CLIDbEnum.MIGRATE:
                    self.db.migrate_migration()
                elif self.mode_enum is CLIDbEnum.UPGRADE:
                    self.db.upgrade_migration()
                else:
                    raise TypeError
        else:
            raise TypeError

    def _run_shell(self):
        """Invoke Puft interactive shell."""
        self.puft.run_shell()

    def _run_app(self):
        self.puft.run()

    def _run_test(self):
        log.info('Run tests')
        pytest.main(self.mode_args)
        
    def _build_all(self) -> None:
        """Send commands to build all given instances."""
        self._build_log()
        self._build_svs()
        self._build_views()
        self._build_errors()
        self._build_emts()
        self._build_shell_processors()
        self._build_cli_cmds()
        self._build_socks()

        # Call postponed build from created App.
        try:
            self.puft.postbuild()
        except NotImplementedError:
            pass

    def _build_log(self) -> None:
        """Call chain to build log."""
        # Try to find log config cell and build log class from it
        if self.config_ies:
            try:
                log_config_ie = NamedIe.find_by_name("log", self.config_ies)
            except ValueError:
                log_config = None
            else:
                # Parse config mapping from cell and append extra configs,
                # if they are given
                app_mode_enum: AppModeEnum
                if type(self.mode_enum) is CLIRunEnum:
                    app_mode_enum = AppModeEnum(self.mode_enum.value) 
                else:
                    # Assign dev app mode for all other app modes
                    app_mode_enum = AppModeEnum.DEV
                log_config = log_config_ie.parse(
                    app_mode_enum=app_mode_enum,
                    root_path=self.root_dir, 
                    update_with=self.extra_configs_by_name.get("log", None)
                )
            self._init_log_class(config=log_config)

    def _init_log_class(self, config: dict | None = None) -> None:
        """Build log with given config.
        
        If config is None, build with default parameters."""
        # Use full or partially (with replacing missing keys from default) given config.
        log_kwargs = self.DEFAULT_LOG_PARAMS
        if config:
            for k, v in config.items():
                log_kwargs[k] = v
        log.configure(**log_kwargs)

    def _build_svs(self) -> None:
        self._run_builtin_sv_ies()
        self._run_custom_sv_ies()

    def _build_socks(self) -> None:
        if self.sock_ies and self.socket_enabled:
            for cell in self.sock_ies:
                socketio: SocketIO = self.socket.get_socketio()

                # Register class for socketio namespace
                # https://flask-socketio.readthedocs.io/en/latest/getting_started.html#class-based-namespaces
                socketio.on_namespace(cell.handler_class(cell.namespace))
                # Also register error handler for the same namespace
                socketio.on_error(cell.namespace)(cell.error_handler) 

    def _perform_db_postponed_setup(self) -> None:
        """Postponed setup is required, because Db uses Flask app to init
        native SQLAlchemy db inside, so it's possible only after App
        initialization.

        The setup_db requires native flask app to work with.
        """
        self.db.setup(flask_app=self.puft.get_native_app())
    
    def _run_builtin_sv_ies(self) -> None:
        for cell in self.builtin_sv_ies:
            # Check for domain's config in given cells by comparing names and
            # apply to sv config if it exists
            config = self._assemble_sv_config(name=cell.name) 

            # Each builtin sv should receive essential fields for their
            # configs, such as root_path, because they cannot import Assembler
            # due to circular import issue and get this fields by themselves
            config["root_path"] = self.root_dir

            # Initialize sv.
            if type(cell) is PuftSvIe:
                # Run special initialization with mode, host and port for Puft
                # sv
                self.puft: Puft = cell.sv_class(
                    mode_enum=cell.mode_enum, host=cell.host, port=cell.port, 
                    config=config,
                    ctx_processor_func=self.ctx_processor_func,
                    each_request_func=self.each_request_func,
                    first_request_func=self.first_request_func)
            elif type(cell) is DbSvIe:
                self.db: Db = cell.sv_class(config=config)
                # Perform Db postponed setup
                self._perform_db_postponed_setup()
            elif type(cell) is SocketSvIe:
                self.socket = cell.sv_class(config=config, app=self.puft)
            else:
                cell.sv_class(config=config)

    def _run_custom_sv_ies(self) -> None:
        if self.sv_ies:
            for cell in self.sv_ies:
                if self.config_ies:
                    sv_config = self._assemble_sv_config(name=cell.name) 
                else:
                    sv_config = {}

                sv: Sv = cell.sv_class(config=sv_config)
                self._custom_svs[cell.sv_class.__name__] = sv

    @property
    def custom_svs(self):
        return self._custom_svs

    def _assemble_sv_config(
            self,
            name: str, is_errors_enabled: bool = False) -> dict[str, Any]:
        """Check for sv's config in config cells by comparing its given
        name and return it as dict.

        If appropriate config hasn't been found, raise ValueError if
        `is_errors_enabled = True` or return empty dict otherwise.
        """
        try:
            config_ie_with_target_name: ConfigIe = NamedIe.find_by_name(
                name, self.config_ies)
        except ValueError:
            # If config not found and errors enabled, raise error.
            if is_errors_enabled:
                message = format_message(
                    "Appropriate config for given name {} hasn't been found.",
                    name)
                raise ValueError(message)
            else:
                config: dict[str, Any] = {}
        else:
            if type(config_ie_with_target_name) is not ConfigIe:
                raise TypeError(format_message(
                    "Type of cell should be ConfigIe, but {} received",
                    type(config_ie_with_target_name)))
            else:
                app_mode_enum: AppModeEnum
                if type(self.mode_enum) is CLIRunEnum:
                    app_mode_enum = AppModeEnum(self.mode_enum.value) 
                else:
                    # Assign dev app mode for all other app modes.
                    app_mode_enum = AppModeEnum.DEV
                config = config_ie_with_target_name.parse(
                    root_path=self.root_dir, 
                    update_with=self.extra_configs_by_name.get(name, None),
                    app_mode_enum=app_mode_enum)
        return config

    def _fetch_yaml_project_version(self) -> str:
        """Fetch project version from info.yaml from the root path and return it. 

        TODO:
            Replace this logic with senseful one. Better use configuration's
            version? Or __init__.py or main.py specified.
        """
        info_data = load_yaml(join_paths(self.root_dir, "./info.yaml"))
        project_version = info_data["version"]
        return project_version

    def _build_views(self) -> None:
        """Build all views by registering them to app."""
        if self.view_ies:
            for view_ie in self.view_ies:
                self.puft.register_view(view_ie)

    def _build_emts(self) -> None:
        """Build emts from given cells and inject Puft application controllers to each."""
        if self.emt_ies:
            for cell in self.emt_ies:
                cell.emt_class(puft=self.puft)

    def _build_shell_processors(self) -> None:
        if self.shell_processors:
            self.puft.register_shell_processor(*self.shell_processors)

    def _build_cli_cmds(self) -> None:
        if self.cli_cmds:
            self.puft.register_cli_cmd(*self.cli_cmds)

    def _build_errors(self) -> None:
        # TODO: Test case when user same error class registered twice (e.g. in
        # duplicate cells)
        wildcard_specified: bool = False

        for error_ie in self.error_ies:
            if type(error_ie.error_class) is Error:
                log.info('Wildcard Error handler specified')
                wildcard_specified = True
            self.puft.register_error(
                error_ie.error_class, error_ie.handler_function)

        # If wildcard handler is not specified, apply the default one
        if not wildcard_specified:
            self.puft.register_error(
                Error, self.default_wildcard_error_handler_func)

        # Register wildcard builin error handler if this function is enabled
        # in config. Do not allow user to specify own builtin error handlers,
        # at least for now (maybe implement this in future)
        if self.puft.wildcard_builtin_error_handler_enabled:
            self.puft.register_error(
                Exception, handle_wildcard_builtin_error)
