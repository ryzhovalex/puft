from dataclasses import dataclass
from pytest import fixture
from puft.core.error.error import Error
from puft.core.test.mock import Mock
from puft.tools.log import log
from puft.core import parsing


class ChildError(Error):
    DEFAULT_MESSAGE = 'Something bad happened in child error!'
    DEFAULT_STATUS_CODE = 405


@dataclass
class ErrorMock(Mock):
    message: str
    status_code: int


@fixture
def error_mock() -> ErrorMock:
    return ErrorMock('Something bad happened!', 400)


@fixture
def error() -> Error:
    return Error()


@fixture
def error_from_mock(error_mock: ErrorMock) -> Error:
    return Error(error_mock.message, error_mock.status_code)


@fixture
def child_error() -> ChildError:
    return ChildError()


@fixture
def child_error_from_mock(error_mock: ErrorMock) -> ChildError:
    return ChildError(error_mock.message, error_mock.status_code)


class TestError():
    def test_expose(self, error: Error):
        exposed: dict = error.expose()

        exposed_error: dict = parsing.parse_key('error', exposed, dict)

        assert exposed_error['name'] == 'Error'
        assert exposed_error['message'] == Error.DEFAULT_MESSAGE
        assert exposed_error['status_code'] == Error.DEFAULT_STATUS_CODE


    def test_expose_from_mock(
            self, error_from_mock: Error, error_mock: ErrorMock):
        exposed: dict = error_from_mock.expose()

        exposed_error: dict = parsing.parse_key('error', exposed, dict)

        assert exposed_error['name'] == 'Error'
        assert exposed_error['message'] == error_mock.message
        assert exposed_error['status_code'] == error_mock.status_code


class TestChildError():
    def test_expose(self, child_error: ChildError):
        exposed: dict = child_error.expose()

        exposed_error: dict = parsing.parse_key('error', exposed, dict)
        log.debug(exposed)

        assert exposed_error['name'] == 'ChildError'
        assert exposed_error['message'] == ChildError.DEFAULT_MESSAGE
        assert exposed_error['status_code'] == ChildError.DEFAULT_STATUS_CODE


    def test_expose_from_mock(
            self, child_error_from_mock: Error, error_mock: ErrorMock):
        exposed: dict = child_error_from_mock.expose()

        exposed_error: dict = parsing.parse_key('error', exposed, dict)

        assert exposed_error['name'] == 'ChildError'
        assert exposed_error['message'] == error_mock.message
        assert exposed_error['status_code'] == error_mock.status_code
