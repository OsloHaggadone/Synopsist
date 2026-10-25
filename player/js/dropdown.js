// The settings page's dropdowns: a button showing what's chosen, and the list of choices, which opens
// under it (or over it, when the player bar leaves too little room below). The list works like a
// list box: while it's open, the up and down arrows move through it, Enter takes the choice, and Esc,
// Tab, or a click anywhere else closes it. Space still plays and pauses, and the left and right
// arrows still seek, as everywhere on the site (app.js leaves alone the keys a list takes).
//
//   <div class="dropdown">
//     <button class="dropdown-button"><span class="dropdown-value"></span>…</button>
//     <ul class="dropdown-list" role="listbox" tabindex="-1" hidden>
//       <li role="option" data-value="…">… <span class="option-name">…</span> …</li> …
//     </ul>
//   </div>
//
// The button shows the chosen option's name, and its colors (.swatches) when it has some.

const GAP = 6; // pixels between the button and the list (as in style.css)

// choose(value) is called when the listener takes a different choice; show(value) marks one chosen.
export function dropdown(root, choose) {
  const button = root.querySelector(".dropdown-button");
  const list = root.querySelector(".dropdown-list");
  const shown = root.querySelector(".dropdown-value");
  const options = [...list.querySelectorAll('[role="option"]')];
  for (const option of options) option.id ||= `${list.id}-${option.dataset.value}`;
  let active = null; // the option the arrow keys are on

  function setActive(option) {
    active?.classList.remove("active");
    active = option;
    active.classList.add("active");
    list.setAttribute("aria-activedescendant", active.id);
  }

  function open() {
    list.hidden = false;
    button.setAttribute("aria-expanded", "true");
    const bar = document.querySelector(".player-bar");
    const floor = bar?.offsetHeight ? bar.getBoundingClientRect().top : innerHeight;
    const box = button.getBoundingClientRect();
    const height = list.offsetHeight + GAP;
    root.classList.toggle("up", box.bottom + height > floor && box.top - height > 0);
    setActive(options.find((option) => option.getAttribute("aria-selected") === "true") ?? options[0]);
    list.focus({ preventScroll: true });
    document.addEventListener("pointerdown", closeOutside, true);
  }

  function close(refocus) {
    if (list.hidden) return;
    if (refocus) button.focus({ preventScroll: true });
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", closeOutside, true);
  }

  function take(option) {
    close(true);
    if (option.getAttribute("aria-selected") !== "true") choose(option.dataset.value);
  }

  const closeOutside = (event) => {
    if (!root.contains(event.target)) close(false);
  };

  button.addEventListener("click", () => (list.hidden ? open() : close(true)));
  button.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    if (list.hidden) open();
  });
  list.addEventListener("click", (event) => {
    const option = event.target.closest('[role="option"]');
    if (option) take(option);
  });
  list.addEventListener("pointermove", (event) => {
    const option = event.target.closest('[role="option"]');
    if (option && option !== active) setActive(option);
  });
  list.addEventListener("keydown", (event) => {
    const at = options.indexOf(active);
    const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: options.length - 1 }[event.key];
    if (to !== undefined) setActive(options[Math.min(Math.max(to, 0), options.length - 1)]);
    else if (event.key === "Enter") take(active);
    else if (event.key === "Escape") close(true);
    else return; // (Tab moves on as usual, and the list closes as the focus leaves it)
    event.preventDefault();
  });
  list.addEventListener("focusout", (event) => {
    if (!root.contains(event.relatedTarget)) close(false);
  });

  return {
    show(value) {
      for (const option of options) option.setAttribute("aria-selected", String(option.dataset.value === value));
      const chosen = options.find((option) => option.dataset.value === value);
      if (chosen) shown.replaceChildren(...[...chosen.querySelectorAll(".swatches, .option-name")].map((node) => node.cloneNode(true)));
    },
  };
}
