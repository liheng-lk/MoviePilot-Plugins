import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "p115transferassistant"
PACKAGE = "p115transferassistant_testpkg"

pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(PLUGIN)]
sys.modules[PACKAGE] = pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", PLUGIN / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


models = _load("models")
resource = _load("resource")
SourceType = models.SourceType
normalize_resource = resource.normalize_resource


def test_magnet_normalizes_tracker_variants_to_same_key():
    a = normalize_resource("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&tr=udp://a")
    b = normalize_resource("magnet:?tr=udp://b&xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567")
    assert a.source_type == SourceType.MAGNET
    assert a.source_key == b.source_key == "0123456789abcdef0123456789abcdef01234567"


def test_ed2k_uses_hash_and_size_as_key():
    item = normalize_resource("ed2k://|file|Demo.S01E03.mkv|123456|0123456789ABCDEF0123456789ABCDEF|/")
    assert item.source_type == SourceType.ED2K
    assert item.filename == "Demo.S01E03.mkv"
    assert item.source_key == "0123456789abcdef0123456789abcdef:123456"


def test_115_share_extracts_password():
    item = normalize_resource("https://115.com/s/sw123abc?password=9xyz")
    assert item.source_type == SourceType.SHARE115
    assert item.share_code == "sw123abc"
    assert item.receive_code == "9xyz"
