// Run with Node.js and Playwright available (Chrome installed).
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const docs = path.resolve(__dirname, "../docs");

(async () => {
  const server = http.createServer((req, res) => {
    const file = path.resolve(docs, "." + (req.url === "/" ? "/index.html" : req.url.split("?")[0]));
    if (!file.startsWith(docs + path.sep) || !fs.existsSync(file)) { res.writeHead(404).end(); return; }
    const type = {".js":"text/javascript", ".html":"text/html", ".png":"image/png", ".svg":"image/svg+xml"}[path.extname(file)];
    res.setHeader("Content-Type", (type || "text/plain") + (type?.startsWith("text") ? "; charset=utf-8" : ""));
    res.end(fs.readFileSync(file));
  }).listen(0, "127.0.0.1");
  await new Promise(resolve => server.once("listening", resolve));
  let browser;
  try {
    browser = await chromium.launch({channel:"chrome", headless:true});
    const context = await browser.newContext({locale:"fr-FR"});
    let releaseRoute;
    await context.route("https://api.github.com/**", route => { releaseRoute = route; });
    await context.route("https://fonts.googleapis.com/**", route => route.abort());
    await context.route("https://flags.restcountries.com/**", route => route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const url = "http://127.0.0.1:" + server.address().port;
    await page.goto(url);
    assert.equal(await page.locator("#idioma").inputValue(), "fr");
    const catalog = await page.evaluate(() => window.siteMessages);
    const keys = Object.keys(catalog.en).sort();
    for (const [language, copy] of Object.entries(catalog)) {
      assert.deepEqual(Object.keys(copy).sort(), keys, language + " missing keys");
      assert(Object.values(copy).every(value => typeof value === "string" && value.trim()));
      await page.selectOption("#idioma", language);
      const failures = await page.evaluate(language => {
        const copy = window.siteMessages[language], failures = [];
        document.querySelectorAll("[data-i18n]").forEach(el => {
          if (el.textContent !== copy[el.dataset.i18n]) failures.push(el.dataset.i18n);
        });
        for (const [suffix, attr] of [["alt","alt"], ["aria","aria-label"], ["title","title"]]) {
          document.querySelectorAll("[data-i18n-" + suffix + "]").forEach(el => {
            if (el.getAttribute(attr) !== copy[el.getAttribute("data-i18n-" + suffix)]) failures.push(attr);
          });
        }
        if (!document.title.includes(copy.headline)) failures.push("document title");
        if (document.querySelector('meta[name="description"]').content !== copy.lead) failures.push("metadata");
        if (!document.getElementById("versao").textContent.includes(copy.portable)) failures.push("release");
        return failures;
      }, language);
      assert.deepEqual(failures, [], language);
      for (const image of await page.locator("[data-screenshot]").all()) {
        assert((await image.getAttribute("src")).includes("/" + language + "/"));
      }
    }
    await page.selectOption("#idioma", "ja");
    await releaseRoute.fulfill({json:{tag_name:"v9.9.9",assets:[{name:"demo.exe",size:1048576,browser_download_url:"https://example.com/demo.exe"}]}});
    await page.waitForFunction(() => document.getElementById("versao").textContent.includes("v9.9.9"));
    assert((await page.locator("#versao").textContent()).includes(catalog.ja.portable));
    await page.selectOption("#idioma", "de");
    assert((await page.locator("#versao").textContent()).includes(catalog.de.portable));
    await page.reload();
    assert.equal(await page.locator("#idioma").inputValue(), "de");
    // All prose must be explicitly translatable. Brands, language names and symbols are exempt.
    const unmarked = await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const result = [];
      let node;
      while ((node = walker.nextNode())) {
        const p = node.parentElement, text = node.textContent.trim();
        if (!text || p.closest("[data-i18n], script, option, #versao, .ic")) continue;
        if (/^(Multi Claude(?: © 2026)?|Richard KPL|GitHub|GPL-3.0|Português, English,|[★⬇◐·]+$)/u.test(text)) continue;
        result.push(text);
      }
      return result;
    });
    assert.deepEqual(unmarked, []);
    await page.setViewportSize({width:390,height:844});
    await page.selectOption("#idioma", "ru");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.route("**/img/ko/*.png", route => route.abort());
    await page.selectOption("#idioma", "ko");
    await page.locator(".galeria").scrollIntoViewIfNeeded();
    await page.waitForFunction(() => [...document.querySelectorAll("[data-screenshot]")].every(img => img.src.includes("/img/en/") && img.complete && img.naturalWidth > 0));
    const fallback = await browser.newContext({locale:"ar-SA"});
    await fallback.route("https://**", route => route.abort());
    await fallback.addInitScript(() => {
      Object.defineProperty(window, "localStorage", {get() { throw new Error("disabled storage"); }});
    });
    const second = await fallback.newPage();
    await second.goto(url);
    assert.equal(await second.locator("#idioma").inputValue(), "en");
    await second.selectOption("#idioma", "pt");
    assert.equal(await second.locator("html").getAttribute("lang"), "pt-BR");
    assert.deepEqual(errors, []);
    console.log("PASS: 10 complete catalogs, every marked text/attribute, no unmarked prose, metadata, late release response, saved language, mobile overflow, English image/language fallbacks and disabled storage.");
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
