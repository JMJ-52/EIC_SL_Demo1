from pathlib import Path

from streamlit_app import required_secret_names, selected_view_for_role


def test_required_secret_names_cover_guest_admin_ai_and_smtp() -> None:
    assert set(required_secret_names()) == {
        "GUEST_USERNAME", "GUEST_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD",
        "OPENAI_API_KEY", "OPENAI_MODEL",
        "TAVILY_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "REQUEST_RECIPIENT_EMAIL",
    }


def test_role_router_never_allows_guest_admin_and_admin_can_switch_both_ways() -> None:
    assert selected_view_for_role("guest", "admin") == "general"
    assert selected_view_for_role("guest", "general") == "general"
    assert selected_view_for_role("admin", "general") == "general"
    assert selected_view_for_role("admin", "admin") == "admin"


def test_sl_is_the_complete_community_cloud_repository_root() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "streamlit_app.py").is_file()
    assert (root / "lifecycle" / "extraction" / "pipeline.py").is_file()
    assert (root / ".streamlit" / "config.toml").is_file()
    assert not any((root / "pages").glob("*.py"))
    config = (root / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "showSidebarNavigation = false" in config
