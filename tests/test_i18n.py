"""Synopsist in Chinese (Simplified), Japanese, and Korean (player/js/i18n.js): every word the site
shows has its three translations in player/i18n/strings.json, with the same blanks ({title}), and the
blocks of index.html marked data-i18n keep their markup. Songs, albums, and artists stay as they are.

A new phrase in the code (t("…"), count(n, "…", "…"), tNodes("…")), in index.html, or in site.js's
tagline and summary needs its line in strings.json; a phrase no longer used loses its line."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

PLAYER = Path(__file__).resolve().parents[1] / "player"
STRINGS = PLAYER / "i18n" / "strings.json"
LANGUAGES = ("zh", "ja", "ko")
LABELS = ("aria-label", "title", "placeholder", "alt")
SKIPPED = {"svg", "script", "style", "kbd"}  # (as js/i18n.js skips them)
# what reads the same in every language: names (the artist's, the site's, its themes, which are albums,
# and the languages' own), and what's written the same way everywhere
AS_IS = {
    "Synopsist", "Oslo Haggadone", "Hollow Journey", "Hollow Journey Beyond", "Planetary Fields", "Eternal Synopsis",
    "English", "简体中文", "日本語", "한국어", "EQ", "EP", "R&B", "A–Z", "Space", "Esc",
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLANK = re.compile(r"\{(\w+)\}")
STRING = r'"((?:[^"\\]|\\.)*)"'


def js_string(text: str) -> str:
    return json.loads(f'"{text}"')


class PageWords(HTMLParser):
    """index.html's words, as js/i18n.js finds them: its texts and labels, and its data-i18n blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, whether its text is left as it is)
        self.texts, self.labels, self.blocks = set(), set(), set()
        self.in_body = False

    def handle_starttag(self, tag, attrs, closed=False):
        attrs = dict(attrs)
        self.in_body = self.in_body or tag == "body"
        if self.in_body and "data-no-i18n" not in attrs:
            self.labels.update(attrs[name] for name in LABELS if attrs.get(name))
        if attrs.get("data-i18n"):
            self.blocks.add(attrs["data-i18n"])  # (translated whole)
        left = bool(self.stack and self.stack[-1][1]) or tag in SKIPPED or "data-no-i18n" in attrs or "data-i18n" in attrs
        if tag not in VOID and not closed:
            self.stack.append((tag, left))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, closed=True)

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        text = " ".join(data.split())
        if self.in_body and text and self.stack and not self.stack[-1][1] and re.search(r"[A-Za-z]", text):
            self.texts.add(text)


def page_words():
    parser = PageWords()
    parser.feed((PLAYER / "index.html").read_text(encoding="utf-8"))
    return parser


def code_words():
    """The phrases the code shows: t("…"), tNodes("…"), and both of count(n, "…", "…")."""
    words = set()
    for path in sorted((PLAYER / "js").glob("*.js")):
        code = path.read_text(encoding="utf-8")
        words.update(js_string(text) for text in re.findall(rf"\b(?:t|tNodes)\(\s*{STRING}", code))
        for one, many in re.findall(rf"\bcount\(\s*[^,\"]+,\s*{STRING}\s*,\s*{STRING}\s*\)", code):
            words.update((js_string(one), js_string(many)))
    return words


def site_words():
    """site.js's own words: its tagline, its few words about the artist, and its summary's points."""
    site = (PLAYER / "site.js").read_text(encoding="utf-8")
    words = {js_string(text) for text in re.findall(rf"\b(?:tagline|bio|title|text):\s*{STRING}", site)}
    return {word for word in words if word}


def tags(html: str) -> list[str]:
    """A block's markup, but for its icons (written {svg1}, … in a translation)."""
    found = re.findall(r"<(?!/)(?!svg|use)[^>]+>", html)
    return sorted(re.sub(r"\s+", " ", tag) for tag in found)


def test_every_phrase_has_its_three_translations():
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    page = page_words()
    wanted = (page.texts | page.labels | code_words() | site_words()) - AS_IS
    missing = sorted(wanted - strings.keys())
    assert not missing, f"not in i18n/strings.json: {missing}"
    blocks = sorted(page.blocks - strings.keys())
    assert not blocks, f"data-i18n blocks not in i18n/strings.json: {blocks}"
    unused = sorted(strings.keys() - wanted - page.blocks)
    assert not unused, f"in i18n/strings.json but no longer used: {unused}"
    for english, ways in strings.items():
        assert sorted(ways) == sorted(LANGUAGES), english
        for language, text in ways.items():
            assert text.strip(), (english, language)


def test_translations_keep_the_blanks_and_the_markup():
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    html = (PLAYER / "index.html").read_text(encoding="utf-8")
    for english, ways in strings.items():
        if english.startswith("@"):
            block = re.search(rf'<(\w+)[^>]*data-i18n="{re.escape(english)}"[^>]*>(.*?)</\1>', html, re.S)
            assert block, english
            inner = block[2]
            icons = len(re.findall(r"<svg\b", inner))
            for language, text in ways.items():
                assert tags(text) == tags(inner), (english, language)
                assert sorted(set(re.findall(r"\{svg(\d+)\}", text))) == [str(n) for n in range(1, icons + 1)], (english, language)
        else:
            blanks = sorted(BLANK.findall(english))
            for language, text in ways.items():
                assert sorted(BLANK.findall(text)) == blanks, (english, language, text)


def test_the_languages_agree():
    """The head of index.html, js/i18n.js, and Settings → Language know the same four."""
    html = (PLAYER / "index.html").read_text(encoding="utf-8")
    i18n = (PLAYER / "js" / "i18n.js").read_text(encoding="utf-8")
    known = re.search(r"const known = \[([^\]]*)\]", html)[1]
    assert re.findall(r'"(\w+)"', known) == ["en", *LANGUAGES]
    names = re.search(r"export const LANGUAGES = \{([^}]*)\}", i18n)[1]
    assert re.findall(r"(\w+):", names) == ["en", *LANGUAGES]
    listed = re.search(r'id="language-list"[^>]*>(.*?)</ul>', html, re.S)[1]
    assert re.findall(r'data-value="(\w+)"', listed) == ["en", *LANGUAGES]
