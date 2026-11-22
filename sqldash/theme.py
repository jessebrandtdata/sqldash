"""The user's palette as CSS custom properties; empty when exotheme is absent."""
import os
from pathlib import Path

try:
    import exotheme
except ImportError:  # exotheme is a soft dependency
    exotheme = None

CONFIG_ENV = "EXOTHEME_CONFIG"


def config_path() -> Path:
    """Return the theme file named by the environment, else the shared default."""
    return Path(os.environ.get(CONFIG_ENV) or Path.home() / ".flextedit" / "theme.json")


def theme_css() -> str:
    """Return `:root` tokens for the active theme, or "" on any failure."""
    if exotheme is None:
        return ""
    try:
        try:
            user = exotheme.parse(config_path().read_text())
        except OSError:
            user = None
        return exotheme.tokens_to_css(exotheme.tokens(user)[1])
    except Exception:
        return ""
