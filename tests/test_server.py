import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from server import app  # noqa: E402

client = TestClient(app)


def test_serves_the_website():
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert 'src="js/app.js"' in page.text
    assert client.get("/js/player.js").status_code == 200
    assert client.get("/no-such-file.mp3").status_code == 404


def test_byte_ranges_so_songs_can_be_seeked():
    full = client.get("/style.css")
    part = client.get("/style.css", headers={"Range": "bytes=10-29"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 10-29/{len(full.content)}"
    assert part.content == full.content[10:30]
