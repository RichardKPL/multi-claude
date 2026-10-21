/* Static-site localization: explicit keys, no traversal or rewriting of text nodes. */
(function () {
  "use strict";
  const messages = window.siteMessages;
  const supported = Object.keys(messages);
  const picker = document.getElementById("idioma");
  const root = document.documentElement;
  let language = "en";
  let release = null;
  function normalize(value) {
    const code = String(value || "").toLowerCase().split(/[-_]/)[0];
    return supported.includes(code) ? code : null;
  }
  function readPreference(key) {
    try { return localStorage.getItem(key); } catch (_) { return null; }
  }
  function savePreference(key, value) {
    try { localStorage.setItem(key, value); } catch (_) {}
  }
  function t(key) {
    return messages[language][key] || messages.en[key];
  }
  function renderRelease() {
    const label = document.getElementById("versao");
    label.textContent = release
      ? [release.tag, t("portable"), release.mb ? release.mb + " MB" : ""].filter(Boolean).join(" · ")
      : t("portable") + " · .exe";
  }
  function setLanguage(value) {
    language = normalize(value) || "en";
    root.lang = language === "pt" ? "pt-BR" : language === "zh" ? "zh-CN" : language;
    picker.value = language;
    document.querySelectorAll("[data-i18n]").forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    for (const [suffix, attribute] of [["alt", "alt"], ["aria", "aria-label"], ["title", "title"]]) {
      document.querySelectorAll("[data-i18n-" + suffix + "]").forEach(el => {
        el.setAttribute(attribute, t(el.getAttribute("data-i18n-" + suffix)));
      });
    }
    document.title = "Multi Claude — " + t("headline");
    document.querySelector('meta[name="description"]').content = t("lead");
    document.querySelector('meta[property="og:description"]').content = t("lead");
    document.querySelectorAll("img[data-screenshot]").forEach(img => {
      img.onerror = function () {
        this.onerror = null;
        this.src = "img/en/" + this.dataset.screenshot;
      };
      img.src = "img/" + language + "/" + img.dataset.screenshot;
    });
    const flag = document.getElementById("idioma-bandeira");
    const countries = {pt:"br", en:"gb", es:"es", fr:"fr", de:"de", it:"it", ru:"ru", ja:"jp", zh:"cn", ko:"kr"};
    flag.onerror = function () { this.onerror = null; this.src = "img/flags/" + language + ".svg"; };
    flag.src = "https://flags.restcountries.com/v5/w160/" + countries[language] + ".png";
    renderRelease();
  }
  picker.addEventListener("change", function () {
    setLanguage(this.value);
    savePreference("site-language", language);
  });
  // Respect a manual choice; otherwise use the browser's primary language or English.
  setLanguage(normalize(readPreference("site-language")) ||
    normalize((navigator.languages || [])[0] || navigator.language) || "en");
  const theme = readPreference("tema");
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  document.getElementById("tema").addEventListener("click", function () {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    savePreference("tema", root.dataset.theme);
  });
  fetch("https://api.github.com/repos/RichardKPL/multi-claude/releases/latest")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data || !data.tag_name) return;
      const exe = (data.assets || []).find(a => /\.exe$/i.test(a.name));
      release = {tag: data.tag_name, mb: exe ? Math.round(exe.size / 1048576) : null};
      if (exe) document.getElementById("baixar").href = exe.browser_download_url;
      renderRelease();
    })
    .catch(() => {});
})();
