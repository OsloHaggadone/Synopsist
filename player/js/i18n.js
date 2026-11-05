// The site in the listener's language: English, as written in index.html and the code, or Chinese
// (Simplified), Japanese, or Korean, from i18n/strings.json, which pairs each English phrase with its
// translations ({"Play next": {"zh": …, "ja": …, "ko": …}}; blanks like {n} are filled in by t()).
// Songs, albums, artists, and the songs' notes stay as they are. index.html's first script picks the
// language (Settings → Language, or else the device's) and starts loading the phrases, and the page is
// shown once they're in; choosing another language reloads the page in it.

export const LANGUAGES = { en: "English", zh: "简体中文", ja: "日本語", ko: "한국어" };
export const language = LANGUAGES[document.documentElement.dataset.language] ? document.documentElement.dataset.language : "en";
export const locale = { en: "en", zh: "zh-CN", ja: "ja", ko: "ko" }[language];

let strings = {};
if (language !== "en") {
  try {
    const all = await (window.synopsistStrings ?? fetch("i18n/strings.json").then((response) => response.json()));
    if (all) strings = Object.fromEntries(Object.entries(all).map(([english, ways]) => [english, ways[language]]).filter(([, text]) => text));
  } catch {
    // (the English, as written)
  }
}

// A phrase in the listener's language, its blanks ({title}) filled from `values`
export function t(text, values) {
  const said = strings[text] ?? text;
  return values ? said.replace(/\{(\w+)\}/g, (blank, name) => (name in values ? values[name] : blank)) : said;
}

// A phrase with something in it that isn't plain text (a word in bold, say): its pieces, in the
// language's order, for el() or replaceChildren(). tNodes("Use {level}", { level: el("b", {}, "High") })
export function tNodes(text, values) {
  return t(text).split(/(\{\w+\})/).filter(Boolean).map((piece) => {
    const name = /^\{(\w+)\}$/.exec(piece)?.[1];
    return name && name in values ? values[name] : piece;
  });
}

export const num = (n) => n.toLocaleString(locale);
// "1 song", "34 songs": count(n, "{n} song", "{n} songs")
export const count = (n, one, many) => t(n === 1 ? one : many, { n: num(n) });

// The page's own words (index.html), once, before the site fills anything in: every text and label
// the phrases have, and the blocks marked data-i18n="@…", whose translation is written with their
// markup (<strong>, a link), their icons in it as {svg1}, {svg2}, … in the English's order.
const LABELS = ["aria-label", "title", "placeholder", "alt"];

export function translatePage(root = document.body) {
  if (language === "en") return;
  for (const node of root.querySelectorAll("[data-i18n]")) {
    const html = strings[node.dataset.i18n];
    if (!html) continue;
    const icons = [...node.querySelectorAll("svg")].map((svg) => svg.outerHTML);
    node.innerHTML = html.replace(/\{svg(\d+)\}/g, (blank, n) => icons[n - 1] ?? "");
  }
  const skip = "svg, script, style, kbd, [data-i18n], [data-no-i18n]";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement.closest(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const said = strings[node.nodeValue.replace(/\s+/g, " ").trim()];
    if (said) node.nodeValue = node.nodeValue.replace(/\S(?:[\s\S]*\S)?/, () => said); // the spaces around it kept
  }
  for (const node of root.querySelectorAll(LABELS.map((name) => `[${name}]`).join())) {
    if (node.closest("[data-no-i18n]")) continue;
    for (const name of LABELS) {
      const said = strings[node.getAttribute(name)];
      if (said) node.setAttribute(name, said);
    }
  }
}

// Settings → Language: kept, then the page again in it
export function setLanguage(code) {
  try {
    localStorage.setItem("synopsist.language", code);
  } catch {}
  location.reload();
}
