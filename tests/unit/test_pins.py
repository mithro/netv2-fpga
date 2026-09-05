"""The installed LiteX family must be exactly the pinned 2026.04 release.

Note: pip/importlib.metadata report PEP 440-normalized version strings, so
the "2026.04" git tag surfaces here as "2026.4" (leading zero stripped from
the release segment). Same release, different spelling.
"""
import importlib.metadata as md

PINNED_VERSION = "2026.4"


def test_litex_is_2026_04():
    assert md.version("litex") == PINNED_VERSION


def test_family_versions_match():
    for pkg in ["litedram", "liteeth", "litepcie", "litespi", "litescope", "liteiclink",
                "litex-boards"]:
        assert md.version(pkg) == PINNED_VERSION, pkg


# The three pythondata packages are deliberately not checked: their version
# strings come from the data they wrap, not from the 2026.04 tag.


def test_migen_importable():
    import migen
    assert hasattr(migen, "Module")
