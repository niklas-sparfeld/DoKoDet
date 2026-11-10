"""Test application factories with explicit non-network analyzer injection."""

from dokodetector_backend.app import create_app
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer


def create_test_app(settings=None, *, recording_catalog_test_activation=False, **kwargs):
    """Build an app without making cloud requests during backend tests."""

    app = create_app(
        settings,
        analyzer=create_local_poc_analyzer(),
        **kwargs,
    )
    if recording_catalog_test_activation:
        app.state.recording_catalog_test_activation = True
        app.state.round_analysis_service.catalog_enabled = True
    return app
