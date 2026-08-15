"""The doc's pictures, as the plugin's store page in the app will draw them.

The app keys a picture by its path under the plugin's doc/ directory, so a reference that names no
file there, or that names it any other way, reaches the reader as a broken image on the store page.
"""
import re
from pathlib import Path

DOC_DIR = Path(__file__).resolve().parent.parent / "doc"
README = DOC_DIR / "README.md"
IMAGES_DIR = DOC_DIR / "images"
IMAGES_PREFIX = "images/"
MARKDOWN_PICTURE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PICTURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})


def pictures_the_doc_shows() -> list[str]:
    return MARKDOWN_PICTURE.findall(README.read_text(encoding="utf-8"))


def test_every_picture_the_doc_shows_is_in_the_repo() -> None:
    missing = [shown for shown in pictures_the_doc_shows() if not (DOC_DIR / shown).is_file()]
    assert not missing, f"the doc shows pictures that are not here: {missing}"


def test_every_picture_is_named_the_way_the_app_resolves_it() -> None:
    astray = [shown for shown in pictures_the_doc_shows() if not shown.startswith(IMAGES_PREFIX)]
    assert not astray, f"the app cannot resolve these to a doc asset: {astray}"


def test_no_picture_ships_that_no_page_shows() -> None:
    shown_pictures = set(pictures_the_doc_shows())
    on_disk = [
        f"{IMAGES_PREFIX}{picture.name}"
        for picture in sorted(IMAGES_DIR.iterdir())
        if picture.suffix.lower() in PICTURE_SUFFIXES
    ]
    unused = [picture for picture in on_disk if picture not in shown_pictures]
    assert not unused, f"pictures shipped with the doc that no page shows: {unused}"
