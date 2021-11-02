from flask.views import MethodView

from ...helpers.logger import logger
from ...tools.noconflict import makecls
from ...helpers.singleton import Singleton
from ...tools.regular import format_error_message


class View(MethodView):
    """Presents API source with HTTP analog methods to be registered in app routing.
    
    Contains general methods `get`, `post`, `put` and `delete` according to same HTTP methods and should be re-implemented in children classes.
    
    Source: [Flask Pluggable Views for APIs](https://flask.palletsprojects.com/en/2.0.x/views/#method-views-for-apis)."""
    __metaclass__ = makecls()
    methods = ["GET", "POST"]  # Methods allowed to access this view.
    decorators = [logger.catch]  # List of decorators to apply to all view's methods.

    def get(self):
        error_message = format_error_message("Method GET is not implemented at view: {}", self.__class__.__name__)
        raise NotImplementedError(error_message)
    
    def post(self):
        error_message = format_error_message("Method POST is not implemented at view: {}", self.__class__.__name__)
        raise NotImplementedError(error_message)

    def put(self):
        error_message = format_error_message("Method PUT is not implemented at view: {}", self.__class__.__name__)
        raise NotImplementedError(error_message)

    def delete(self):
        error_message = format_error_message("Method DELETE is not implemented at view: {}", self.__class__.__name__)
        raise NotImplementedError(error_message)