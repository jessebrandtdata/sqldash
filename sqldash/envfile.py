"""Load NAME=value lines from a key file into an environment mapping."""
import re
from pathlib import Path
from typing import MutableMapping

_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def default_path(environ) -> Path:
    custom = environ.get("SQLDASH_ENV")
    return Path(custom) if custom else Path.home() / ".config" / "sqldash" / "env"


def load_env_file(path: Path, environ: MutableMapping[str, str]) -> list[str]:
    """Set names missing from environ; return the names set."""
    try:
        text = Path(path).read_text()
    except OSError:
        return []
    names = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in environ:
            continue
        environ[name] = value
        names.append(name)
    return names
