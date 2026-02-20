# -*- coding: utf-8 -*-
"""
    flask.app
    ~~~~~~~~

    This module implements the central WSGI application object.

    :copyright: 2010 Pallets
    :license: BSD-3-Clause
"""
import os
import sys
import typing as t
from datetime import timedelta

from . import cli
from .config import Config, ConfigAttribute
from .ctx import AppContext, RequestContext
from .globals import _app_ctx_stack, _request_ctx_stack
from .helpers import (
    _endpoint_from_view_func,
    find_package,
    get_debug_flag,
    get_flashed_messages,
    url_for,
)
from .json import JSONDecoder as _JSONDecoder
from .json import JSONEncoder as _JSONEncoder
from .logging import create_logger
from .sessions import SecureCookieSessionInterface
from .signals import appcontext_tearing_down, request_finished, request_started
from .typing import AfterRequestCallable, BeforeFirstRequestCallable
from .typing import BeforeRequestCallable, TeardownCallable
from .typing import TemplateFilterCallable, TemplateGlobalCallable, TemplateTestCallable
from .typing import URLDefaultCallable, URLValuePreprocessorCallable
from .wrappers import Request, Response

if t.TYPE_CHECKING:
    from .testing import FlaskClient

F = t.TypeVar("F", bound=t.Callable[..., t.Any])
T_route = t.TypeVar("T_route", bound=t.Callable[..., t.Any])
T_error_handler = t.TypeVar("T_error_handler", bound=t.Callable[..., t.Any])
T_shell_context_processor = t.TypeVar("T_shell_context_processor", bound=t.Callable[..., t.Any])


def setupmethod(f: F) -> F:
    """Wraps a method so that it performs a check in debug mode that the
    setup has not yet been called.
    """
    def wrapper_func(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        if self.debug and self._got_first_request:
            raise AssertionError(
                "A setup function was called after the first request was handled."
                " This usually indicates a bug in the application where a module"
                " was not imported and decorators or other functionality was run"
                " too late. To fix this make sure to import all your view modules,"  # noqa: B950
                " database models and everything related at a central place before"
                " the application starts serving requests."
            )
        return f(self, *args, **kwargs)

    return t.cast(F, wrapper_func)


class Flask:
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an :file:`__init__.py` file inside) or a standard module (just a single
    file).
    """

    #: The class that is used for request objects.  See :class:`~flask.Request`
    #: for more information.
    request_class = Request  # type: ignore[assignment]

    #: The class that is used for response objects.  See :class:`~flask.Response`
    #: for more information.
    response_class = Response  # type: ignore[assignment]

    #: The class that is used for the ``json`` attribute of the application.
    #: By default this is an instance of :class:`flask.helpers.JSONProvider`.
    #: Since Flask 2.2 this can be customized by assigning an instance of a
    #: subclass of :class:`flask.helpers.JSONProvider` to this attribute.
    json_provider_class = None  # type: ignore[assignment]

    #: The debug flag.  Set this to ``True`` to enable debugging of the
    #: application.  In debug mode the debugger will kick in when an unhandled
    #: exception occurs and the integrated server will automatically reload the
    #: application if changes in the code are detected.
    #:
    #: This attribute can also be configured from the config with the ``DEBUG``
    #: configuration key.  Defaults to the value of the
    #: :attr:`app.debug` attribute if not set.
    debug = ConfigAttribute("DEBUG")  # type: ignore[assignment]

    #: The testing flag.  Set this to ``True`` to enable the test mode of
    #: Flask extensions.
    #:
    #: This attribute can also be configured from the config with the ``TESTING``
    #: configuration key.  Defaults to the value of the
    #: :attr:`app.testing` attribute if not set.
    testing = ConfigAttribute("TESTING")  # type: ignore[assignment]

    #: If a secret key is set, cryptographic components can use it to sign
    #: cookies and other things. Set this to a complex random value when you
    #: want to use the secure cookie for instance.
    #:
    #: This attribute can also be configured from the config with the
    #: ``SECRET_KEY`` configuration key. Defaults to the value of the
    #: :attr:`app.secret_key` attribute if not set.
    secret_key = ConfigAttribute("SECRET_KEY")  # type: ignore[assignment]

    #: The name of the session cookie. This can be changed by setting the
    #: ``SESSION_COOKIE_NAME`` config key.
    #:
    #: .. versionadded:: 0.8
    session_cookie_name = ConfigAttribute("SESSION_COOKIE_NAME")  # type: ignore[assignment]

    #: A :class:`~datetime.timedelta` which is used to set the expiration
    #: date of a permanent session. The default is 31 days which makes a
    #: permanent session survive for roughly one month.
    #:
    #: This attribute can also be configured from the config with the
    #: ``PERMANENT_SESSION_LIFETIME`` configuration key.  Defaults to
    #: ``timedelta(days=31)``
    permanent_session_lifetime = ConfigAttribute(
        "PERMANENT_SESSION_LIFETIME"
    )  # type: ignore[assignment]

    #: Options that are passed directly to the Jinja2 environment.
    #:
    #: .. versionadded:: 0.5
    jinja_options = {}  # type: t.Dict[str, t.Any]

    #: The name of the logger to use. By default the logger name is the
    #: package name passed to the constructor.
    #:
    #: .. versionadded:: 0.4
    logger_name = None  # type: t.Optional[str]

    default_config = {
        "DEBUG": None,
        "TESTING": False,
        "PROPAGATE_EXCEPTIONS": None,
        "PRESERVE_CONTEXT_ON_EXCEPTION": None,
        "SECRET_KEY": None,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
        "USE_X_SENDFILE": False,
        "SEND_FILE_MAX_AGE_DEFAULT": None,
        "SERVER_NAME": None,
        "APPLICATION_ROOT": "/",
        "SESSION_COOKIE_NAME": "session",
        "SESSION_COOKIE_DOMAIN": None,
        "SESSION_COOKIE_PATH": None,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_SAMESITE": None,
        "SESSION_REFRESH_EACH_REQUEST": True,
        "MAX_CONTENT_LENGTH": None,
        "SEND_FILE_MAX_AGE_DEFAULT": None,
        "TRAP_BAD_REQUEST_ERRORS": None,
        "TRAP_HTTP_EXCEPTIONS": False,
        "EXPLAIN_TEMPLATE_LOADING": False,
        "PREFERRED_URL_SCHEME": "http",
        "JSON_AS_ASCII": True,
        "JSON_SORT_KEYS": True,
        "JSONIFY_PRETTYPRINT_REGULAR": False,
        "JSONIFY_MIMETYPE": "application/json",
        "TEMPLATES_AUTO_RELOAD": None,
        "MAX_COOKIE_SIZE": 4093,
    }  # type: t.Dict[str, t.Any]

    def __init__(
        self,
        import_name: str,
        static_url_path: t.Optional[str] = None,
        static_folder: t.Optional[str] = "static",
        static_host: t.Optional[str] = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: t.Optional[str] = "templates",
        instance_path: t.Optional[str] = None,
        instance_relative_config: bool = False,
        root_path: t.Optional[str] = None,
    ) -> None:
        _app_ctx_stack.push(self._app_ctx = AppContext(self))
        self.import_name = import_name
        self.root_path = root_path or self._find_root_path()
        self._static_folder = static_folder
        self._static_url_path = static_url_path
        self._static_host = static_host
        self.instance_path = instance_path or self._find_instance_path()
        self.instance_relative_config = instance_relative_config
        self.config = self.make_config()
        self.debug = get_debug_flag()
        self.testing = False
        self.secret_key = None
        self._got_first_request = False
        self._before_request_funcs = {}  # type: t.Dict[t.Optional[str], t.List[BeforeRequestCallable]]
        self._after_request_funcs = {}  # type: t.Dict[t.Optional[str], t.List[AfterRequestCallable]]
        self._before_first_request_funcs = (
            []
        )  # type: t.List[BeforeFirstRequestCallable]
        self._teardown_appcontext_funcs = (
            []
        )  # type: t.List[TeardownCallable]
        self._teardown_request_funcs = (
            []
        )  # type: t.Dict[t.Optional[str], t.List[TeardownCallable]]
        self._url_default_functions = {}  # type: t.Dict[t.Optional[str], t.List[URLDefaultCallable]]
        self._url_value_preprocessors = (
            {}
        )  # type: t.Dict[t.Optional[str], t.List[URLValuePreprocessorCallable]]
        self._template_context_processors = (
            {}
        )  # type: t.Dict[t.Optional[str], t.List[t.Callable[..., t.Dict[str, t.Any]]]]
        self._shell_context_processors = (
            []
        )  # type: t.List[T_shell_context_processor]
        self._url_map = None  # type: t.Optional[t.Any]
        self._blueprints = {}  # type: t.Dict[str, "Blueprint"]
        self.extensions = {}  # type: t.Dict[str, t.Any]
        self.url_map_class = None  # type: t.Optional[t.Any]
        self._error_handlers = {}  # type: t.Dict[t.Optional[int], t.Dict[t.Type[Exception], T_error_handler]]
        self.url_build_error_handlers = (
            []
        )  # type: t.List[t.Callable[[Exception, str, t.Dict[str, t.Any]], str]]
        self.before_request_funcs = None  # type: ignore[assignment]
        self.after_request_funcs = None  # type: ignore[assignment]
        self.teardown_request_funcs = None  # type: ignore[assignment]
        self.teardown_appcontext_funcs = None  # type: ignore[assignment]
        self.url_default_functions = None  # type: ignore[assignment]
        self.url_value_preprocessors = None  # type: ignore[assignment]
        self.template_context_processors = None  # type: ignore[assignment]
        self.shell_context_processors = None  # type: ignore[assignment]
        self.error_handler_spec = None  # type: ignore[assignment]
        self.view_functions = {}  # type: t.Dict[str, t.Callable[..., t.Any]]
        self.cli = cli.FlaskGroup()
        self.json_encoder = _JSONEncoder
        self.json_decoder = _JSONDecoder
        self.json_provider_class = None
        self.session_interface = SecureCookieSessionInterface()
        self._logger = None  # type: t.Optional[logging.Logger]
        self.name = self.__class__.__name__
        self.host_matching = host_matching
        self.subdomain_matching = subdomain_matching
        self.template_folder = template_folder
        self.jinja_env = None  # type: t.Optional[t.Any]
        self._logger = None
        self._got_first_request = False
        self._before_request_funcs = {}
        self._after_request_funcs = {}
        self._before_first_request_funcs = []
        self._teardown_appcontext_funcs = []
        self._teardown_request_funcs = {}
        self._url_default_functions = {}
        self._url_value_preprocessors = {}
        self._template_context_processors = {}
        self._shell_context_processors = []
        self._url_map = None
        self._blueprints = {}
        self.extensions = {}
        self.url_map_class = None
        self._error_handlers = {}
        self.url_build_error_handlers = []
        self.before_request_funcs = None
        self.after_request_funcs = None
        self.teardown_request_funcs = None
        self.teardown_appcontext_funcs = None
        self.url_default_functions = None
        self.url_value_preprocessors = None
        self.template_context_processors = None
        self.shell_context_processors = None
        self.error_handler_spec = None
        self.view_functions = {}
        self.cli = cli.FlaskGroup()
        self.json_encoder = _JSONEncoder
        self.json_decoder = _JSONDecoder
        self.json_provider_class = None
        self.session_interface = SecureCookieSessionInterface()
        self._logger = None
        self.name = self.__class__.__name__
        self.host_matching = host_matching
        self.subdomain_matching = subdomain_matching
        self.template_folder = template_folder
        self.jinja_env = None
        self._logger = None

    def _find_root_path(self) -> str:
        """Find the path to the package or module."""
        module = sys.modules.get(self.import_name)
        if module is not None and hasattr(module, "__file__"):
            return os.path.dirname(os.path.abspath(module.__file__))
        return os.getcwd()

    def _find_instance_path(self) -> str:
        """Find the path to the instance folder."""
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(self.root_path, "instance")
        return os.path.join(prefix, "var", f"{self.name}-instance")

    def make_config(self) -> Config:
        """Create the configuration object."""
        return Config(self.root_path, self.default_config)

    @property
    def logger(self) -> "logging.Logger":
        """A :class:`logging.Logger` object for this application. The
        default configuration is to log to stderr if the application is
        in debug mode. This logger can be used to log application errors.
        """
        if self._logger is None:
            self._logger = create_logger(self)
        return self._logger

    def run(
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        debug: t.Optional[bool] = None,
        load_dotenv: bool = True,
        **options: t.Any,
    ) -> None:
        """Runs the application on a local development server.

        Do not use ``run()`` in a production setting.
        """
        from werkzeug.serving import run_simple

        if host is None:
            host = "127.0.0.1"
        if port is None:
            server_name = self.config.get("SERVER_NAME")
            if server_name:
                port = int(server_name.split(":")[-1]) if ":" in server_name else None
            if port is None:
                port = 5000
        if debug is None:
            debug = self.debug

        options.setdefault("use_reloader", debug)
        options.setdefault("use_debugger", debug)
        options.setdefault("threaded", True)

        cli.show_server_banner(self.debug, self.name)

        run_simple(
            host,
            t.cast(int, port),
            self,
            **options,
        )

    def test_client(self, use_cookies: bool = True) -> "FlaskClient":
        """Creates a test client for this application."""
        from .testing import FlaskClient

        return FlaskClient(self, use_cookies=use_cookies)

    def open_session(self, request: Request) -> t.Dict[str, t.Any]:
        """Create or open a session."""
        return self.session_interface.open_session(self, request)

    def save_session(self, session: t.Dict[str, t.Any], response: Response) -> None:
        """Save the session."""
        return self.session_interface.save_session(self, session, response)
