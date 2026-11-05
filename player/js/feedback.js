// The feedback page (#feedback): how satisfied the listener is with the site, out of five stars, and
// anything they'd like to say, sent anonymously. A rating or a few words is enough, or both. Only
// those and the site's language are sent, as JSON (text/plain, which a page may send to another site
// without asking first), to the contact form's Worker on Cloudflare (SITE.feedbackUrl; the portfolio's
// contact-worker/), which emails them to the artist and keeps nothing. No name, email, or listener
// ID goes with them, and there's no one to reply to.

import { SITE } from "../site.js";
import { el, icon } from "./dom.js";
import { count, language, t } from "./i18n.js";

export function wireFeedback() {
  const form = document.getElementById("feedback-form");
  const stars = document.getElementById("feedback-stars");
  const status = document.getElementById("feedback-status");
  const send = document.getElementById("feedback-send");
  if (!form || !SITE.feedbackUrl) return;

  // the stars: a radio button each, so the arrow keys move along them, as in any choice of one
  stars.replaceChildren(...[1, 2, 3, 4, 5].map((n) => el("label", { class: "star" },
    el("input", { type: "radio", name: "rating", value: String(n), class: "visually-hidden", "aria-label": count(n, "{n} star", "{n} stars") }),
    icon("star"))));
  const rating = () => Number(form.elements.rating.value) || null;
  const showStars = () => {
    for (const [i, star] of stars.querySelectorAll(".star").entries()) star.classList.toggle("on", i < (rating() ?? 0));
  };

  function say(text, isError = false) {
    status.textContent = text;
    status.classList.toggle("error", isError);
  }

  stars.addEventListener("change", () => {
    showStars();
    if (status.classList.contains("error")) say("");
  });
  form.elements.message.addEventListener("input", () => status.classList.contains("error") && say(""));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = { rating: rating(), message: form.elements.message.value.trim(), language, _honey: form.elements._honey.value };
    if (!data.rating && !data.message) {
      say(t("Choose a rating, or write a few words."), true);
      return;
    }
    if (data._honey) return; // a spam bot filled in the hidden field
    if (navigator.onLine === false) {
      say(t("You're offline: sending feedback needs a connection."), true);
      return;
    }
    send.disabled = true;
    say(t("Sending…"));
    try {
      const response = await fetch(SITE.feedbackUrl, { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify(data) });
      const result = await response.json();
      if (!response.ok || result.success !== true) throw new Error(result.message);
      form.reset();
      showStars();
      say(t("Thanks! Your feedback is on its way."));
    } catch {
      say(t("It didn't send. Please try again in a moment."), true);
    } finally {
      send.disabled = false;
    }
  });
}
