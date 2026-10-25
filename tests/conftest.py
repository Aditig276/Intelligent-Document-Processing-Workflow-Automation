import pytest


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    """Every test writes uploads/results into its own temp folder."""
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def stored_files(media_root):
    """All regular files below MEDIA_ROOT (empty list if it does not exist)."""
    if not media_root.exists():
        return []
    return [p for p in media_root.rglob("*") if p.is_file()]


@pytest.fixture
def media_files(isolated_media):
    return lambda: stored_files(isolated_media)


@pytest.fixture
def require_url():
    """Skip a test when the merged project does not expose a URL name yet."""
    from django.urls import NoReverseMatch, reverse

    def _require(name, **kwargs):
        try:
            return reverse(name, kwargs=kwargs or None)
        except NoReverseMatch:
            pytest.skip(f"URL name '{name}' is not wired up in this checkout")

    return _require
