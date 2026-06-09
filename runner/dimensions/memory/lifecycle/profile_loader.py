"""YAML profile loader for v0.2.5 bundle deployment profiles.

Each profile YAML specifies the configurable knobs for the
v0.2.5-comprehensive-graph-tuned bundle. The five starter profiles
shipped at runner/dimensions/memory/lifecycle/profiles/:

  general-default.yaml          conservative out-of-the-box
  finance-aggressive.yaml       financial domain; short TTLs
  clinical-conservative.yaml    healthcare; multi-year retention
  customer-conversations.yaml   Mem0-shape conversations
  local-model-conservative.yaml local 7B-class LLMs (noisier extraction)

A customer picks one profile axis (domain × downstream × LLM × setup)
and the loader materializes a V02xConfig from the matching YAML.

Uses Python's stdlib only (parses a restricted YAML subset). No
external dependencies. For complex YAML (anchors, custom tags), swap
in PyYAML.
"""
from __future__ import annotations
import re
from pathlib import Path

from .comprehensive_graph_tuned import ComprehensiveGraphTunedGC, V02xConfig


PROFILES_DIR = Path(__file__).resolve().parent / "profiles"


def _parse_simple_yaml(text: str) -> dict:
    """Parse a restricted YAML subset: top-level key-value pairs with
    optional comments. Values are int / float / bool / str.

    For the v0.2.5 profile shape (flat key-value), this is enough.
    Skips nested mappings and lists.
    """
    result: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line or line.startswith(" "):
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, val_str = m.group(1), m.group(2).strip()
        if not val_str:
            continue
        # Type coercion
        if val_str.lower() in ("true", "yes"):
            result[key] = True
        elif val_str.lower() in ("false", "no"):
            result[key] = False
        else:
            try:
                if "." in val_str or "e" in val_str.lower():
                    result[key] = float(val_str)
                else:
                    result[key] = int(val_str)
            except ValueError:
                result[key] = val_str.strip('"').strip("'")
    return result


def from_yaml(profile_path: str | Path) -> V02xConfig:
    """Load a V02xConfig from a YAML profile file.

    The YAML's keys must match V02xConfig field names. Missing fields
    fall back to V02xConfig defaults.
    """
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")
    raw = _parse_simple_yaml(path.read_text())
    # Filter to only known V02xConfig fields
    valid_fields = {f.name for f in V02xConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_fields}
    return V02xConfig(**filtered)


def build_from_profile(profile_name: str) -> ComprehensiveGraphTunedGC:
    """Build a v0.2.5 bundle from a named profile in PROFILES_DIR.

    Args:
      profile_name: name of profile (without .yaml suffix), e.g.
        'general-default', 'finance-aggressive'.

    Raises FileNotFoundError if no such profile ships.
    """
    profile_path = PROFILES_DIR / f"{profile_name}.yaml"
    config = from_yaml(profile_path)
    return ComprehensiveGraphTunedGC(config=config)


def list_profiles() -> list[str]:
    """Names of the starter profiles available in PROFILES_DIR."""
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))
