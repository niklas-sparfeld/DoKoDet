"""Test application factories with explicit non-network analyzer injection."""

from dokodetector_backend.app import create_app
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer


def create_test_app(settings=None, **kwargs):
    """Build an app without making cloud requests during backend tests."""

    return create_app(
        settings,
        analyzer=create_local_poc_analyzer(),
        **kwargs,
    )
