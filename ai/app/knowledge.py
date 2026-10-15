"""Generic Python-ecosystem hints. These are CANDIDATES and context only — Gemma makes the decision and the
sandbox verifies it. Nothing here may reference a specific target repository (see docs/AGENT_RULES.md §4)."""
from __future__ import annotations

# import name -> distribution name, where they differ
IMPORT_TO_DIST = {
    "yaml": "pyyaml", "dateutil": "python-dateutil", "bs4": "beautifulsoup4", "PIL": "pillow",
    "sklearn": "scikit-learn", "cv2": "opencv-python", "pkg_resources": "setuptools", "attr": "attrs",
    "dotenv": "python-dotenv", "jose": "python-jose", "jwt": "pyjwt", "magic": "python-magic",
    "Crypto": "pycryptodome", "OpenSSL": "pyopenssl", "google.protobuf": "protobuf", "serial": "pyserial",
    "usb": "pyusb", "git": "gitpython", "markupsafe": "markupsafe", "multipart": "python-multipart",
    "nose": "nose", "docx": "python-docx", "slugify": "python-slugify",
}

# distribution -> import names, where they differ
DIST_TO_IMPORTS = {
    "pyyaml": ["yaml"], "python-dateutil": ["dateutil"], "beautifulsoup4": ["bs4"], "pillow": ["PIL"],
    "scikit-learn": ["sklearn"], "setuptools": ["setuptools", "pkg_resources"], "attrs": ["attr", "attrs"],
    "python-dotenv": ["dotenv"], "pyjwt": ["jwt"], "pycryptodome": ["Crypto"], "pyopenssl": ["OpenSSL"],
    "gitpython": ["git"], "python-multipart": ["multipart"], "python-docx": ["docx"],
    "python-slugify": ["slugify"], "opencv-python": ["cv2"], "protobuf": ["google.protobuf"],
}

# packages that are used as tools/runners rather than imported
TOOL_PACKAGES = {
    "pytest", "nose", "nose2", "setuptools", "wheel", "pip", "black", "flake8", "mypy", "coverage", "tox",
    "pylint", "isort", "ruff", "pre-commit", "twine", "build", "sphinx", "pytest-cov", "uv",
}

DEPRECATED_PACKAGES = {
    "nose": "Unmaintained since 2015; does not run on Python 3.10+ (uses removed stdlib APIs). Successor: pytest.",
    "appdirs": "Archived; the maintained fork is platformdirs.",
    "toml": "Unmaintained and does not support TOML 1.0; tomllib (stdlib 3.11+) reads TOML, tomli-w writes it.",
    "six": "Python 2/3 compatibility layer; unnecessary on Python 3-only projects.",
    "mock": "Backport of unittest.mock (stdlib since 3.3).",
    "simplejson": "json in the stdlib covers almost all uses.",
    "pycrypto": "Unmaintained with known vulnerabilities; use pycryptodome or cryptography.",
    "futures": "Backport of concurrent.futures (stdlib).",
    "enum34": "Backport of enum (stdlib).",
    "typing": "Backport; typing is in the stdlib.",
    "pathlib2": "Backport of pathlib (stdlib).",
    "dataclasses": "Backport; dataclasses is stdlib since 3.7.",
    "pytz": "zoneinfo is in the stdlib since 3.9.",
    "distutils": "Removed from the stdlib in 3.12.",
}

# distribution -> candidate replacements (strings; "(stdlib)" marks standard library)
CANDIDATES = {
    "toml": ["tomllib (stdlib, read-only, Python 3.11+)", "tomli", "tomli-w (writing)"],
    "appdirs": ["platformdirs"],
    "six": ["(remove: Python 3 only)"],
    "chardet": ["charset-normalizer", "upgrade chardet"],
    "nose": ["pytest"],
    "mock": ["unittest.mock (stdlib)"],
    "simplejson": ["json (stdlib)"],
    "pytz": ["zoneinfo (stdlib)"],
    "pycrypto": ["pycryptodome", "cryptography"],
    "setuptools": ["importlib.resources (stdlib) instead of pkg_resources", "importlib.metadata (stdlib)"],
    "requests": ["upgrade requests", "httpx"],
    "jinja2": ["upgrade jinja2 to 3.x"],
    "pydantic": ["upgrade pydantic to 2.x (bump-pydantic codemod)", "pydantic.v1 compatibility shim"],
    "idna": ["upgrade idna"],
    "pyyaml": ["upgrade pyyaml"],
}

STDLIB_REPLACEMENTS = {
    "toml": ("tomllib", (3, 11)), "mock": ("unittest.mock", (3, 3)), "simplejson": ("json", (3, 0)),
    "pytz": ("zoneinfo", (3, 9)), "enum34": ("enum", (3, 4)), "futures": ("concurrent.futures", (3, 2)),
    "pathlib2": ("pathlib", (3, 4)), "dataclasses": ("dataclasses", (3, 7)), "typing": ("typing", (3, 5)),
    "six": ("(none needed on Python 3)", (3, 0)),
}

# qualified symbol (module or module.attr) -> advice
DEPRECATED_APIS = {
    "pkg_resources": "pkg_resources is deprecated and slated for removal from setuptools; use importlib.resources / importlib.metadata.",
    "pydantic.validator": "Pydantic v1 API; v2 uses field_validator.",
    "pydantic.root_validator": "Pydantic v1 API; v2 uses model_validator.",
    "jinja2.Markup": "Removed in Jinja2 3.1; import Markup from markupsafe.",
    "jinja2.contextfilter": "Removed in Jinja2 3.1; use pass_context.",
    "jinja2.evalcontextfilter": "Removed in Jinja2 3.1; use pass_eval_context.",
    "distutils": "Removed from the stdlib in Python 3.12.",
    "imp": "Removed from the stdlib in Python 3.12; use importlib.",
    "asyncio.get_event_loop": "Deprecated outside a running loop; use asyncio.run / get_running_loop.",
    "datetime.datetime.utcnow": "Deprecated in 3.12; use datetime.now(timezone.utc).",
}

# pydantic-style inner `class Config:` on BaseModel subclasses (v1 configuration style)
V1_CONFIG_CLASS_PACKAGES = {"pydantic": "Inner `class Config` is Pydantic v1 style; v2 uses model_config = ConfigDict(...)."}


def candidates_for(dist: str) -> list[str]:
    return CANDIDATES.get(dist, [])


def import_names_for(dist: str) -> list[str]:
    if dist in DIST_TO_IMPORTS:
        return DIST_TO_IMPORTS[dist]
    return [dist.replace("-", "_").lower()]


def dist_for_import(mod: str) -> str:
    return IMPORT_TO_DIST.get(mod, mod).lower().replace("_", "-")
