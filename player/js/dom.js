// Small helpers for building the page, shared by the modules that draw it.

// 3:07
export function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.filter((child) => child != null && child !== false));
  return node;
}

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

export function setIcon(button, name) {
  button.querySelector("use").setAttribute("href", `#i-${name}`);
}

// Play a CSS animation again by taking its class off and putting it back.
export function restart(node, cls) {
  if (!node) return;
  node.classList.remove(cls);
  node.getBoundingClientRect();
  node.classList.add(cls);
}

// The same, for animations that play again and again (each new song, play and pause): the class
// comes off by itself when the animation ends (the node's own, or `endsOn`'s), so putting it back on
// is all it takes; one
// that's still running just carries on (when songs are skipped quickly, a new cover appears in the
// unfolding already under way, and one swell of light covers them all). restart() has to lay out the
// page to start one over, which costs a frame when it happens a few times in a row.
export function replay(node, cls, endsOn = node) {
  if (!node || node.classList.contains(cls)) return;
  node.classList.add(cls);
  const ended = (event) => {
    if (event.target !== endsOn || event.pseudoElement) return;
    node.classList.remove(cls);
    node.removeEventListener("animationend", ended);
  };
  node.addEventListener("animationend", ended);
}
