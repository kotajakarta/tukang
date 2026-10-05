import pytest
from app.main import app
from app.core.security import require_user
from app.models.user import CurrentUser

@pytest.fixture(autouse=True)
def authenticated_user(request):
    """API tests run as a logged-in user unless marked with @pytest.mark.real_auth."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[require_user] = lambda: CurrentUser(id=0, username="test")
    yield
    app.dependency_overrides.pop(require_user, None)

def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: run without the authenticated-user override")
