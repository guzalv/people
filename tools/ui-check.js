// Drive the SPA in jsdom against the live server: exercise routing, the
// autocomplete-create combobox, facts, membership, and the meal-plan report.
"use strict";
const { JSDOM } = require("jsdom");
const fs = require("fs");

const BASE = "http://127.0.0.1:8766";
const errors = [];

async function main() {
  const html = await (await fetch(BASE + "/")).text();
  const dom = new JSDOM(html, { url: BASE + "/", runScripts: "outside-only" });
  const { window } = dom;
  const { document } = window;

  window.fetch = (p, o) => fetch(new URL(p, BASE), o);
  window.confirm = () => true;
  window.prompt = () => "severe, carries epipen";
  window.addEventListener("error", (e) => errors.push("window error: " + e.message));
  process.on("unhandledRejection", (e) => errors.push("unhandled rejection: " + e));

  window.eval(fs.readFileSync(process.env.APP_JS, "utf8"));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(desc, fn, ms = 4000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      let v;
      try { v = fn(); } catch (e) { v = null; }
      if (v) return v;
      await sleep(40);
    }
    throw new Error("timeout waiting for: " + desc);
  }
  const q = (sel) => document.querySelector(sel);
  const byText = (sel, text) =>
    [...document.querySelectorAll(sel)].find((n) => n.textContent.includes(text));
  // suggestion buttons render "label" + optional hint span — match label exactly
  const suggestion = (label) =>
    [...document.querySelectorAll(".combo-list button")].find((b) => {
      const t = b.textContent.trim();
      return t === label || t.startsWith(label + "\n") || t.startsWith(label + " ");
    });
  const type = (input, text) => {
    input.value = text;
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  };
  const pointer = (n) => n.dispatchEvent(new window.Event("pointerdown", { bubbles: true }));
  const focus = (input) => input.focus(); // real focus so activeElement matches

  // --- home renders (fresh DB: empty) ---
  await waitFor("home empty state", () => byText(".empty", "No people"));
  console.log("✓ home renders");

  // --- create a person through the UI ---
  q('button[data-add="persons"]').click();
  const form = await waitFor("create form", () => q("form.card"));
  type(form.querySelector("input"), "Alice");
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor("person view", () => byText("h1", "Alice"));
  console.log("✓ person created via UI, routed to #" + window.location.hash);

  // --- attribute combobox: suggest existing name, add new value ---
  let attrInput = await waitFor("attr input", () => q('.combo input[placeholder^="attribute"]'));
  focus(attrInput); type(attrInput, "lik");
  const likesBtn = await waitFor("likes suggestion", () => suggestion("likes"));
  pointer(likesBtn);
  let valInput = q('.combo input[placeholder="value…"]');
  focus(valInput); type(valInput, "tomatoes");
  const createBtn = await waitFor("create row", () => valInput.closest(".combo").querySelector(".combo-list button.create"));
  pointer(createBtn);
  await waitFor("tomatoes chip", () => byText(".chip", "tomatoes"));
  console.log("✓ likes: tomatoes added via combobox create");

  // --- new attribute gets polarity guessed (allergies -> avoid) ---
  attrInput = q('.combo input[placeholder^="attribute"]');
  focus(attrInput); type(attrInput, "allergies");
  await sleep(250);
  valInput = q('.combo input[placeholder="value…"]');
  focus(valInput); type(valInput, "shellfish");
  pointer(await waitFor("create shellfish", () => valInput.closest(".combo").querySelector(".combo-list button.create")));
  await waitFor("shellfish avoid chip", () =>
    [...document.querySelectorAll(".chip.avoid")].some((c) => c.textContent.includes("shellfish")));
  console.log("✓ new attribute 'allergies' guessed as avoid, chip styled");

  // --- note editing via chip tap (prompt stub) ---
  const chipVal = byText(".chip .val", "shellfish");
  chipVal.click();
  await waitFor("note shown", () => byText(".chip .note", "epipen"));
  console.log("✓ note edited via chip tap");

  // --- fact ---
  type(q('input[placeholder="something they mentioned…"]'), "just got a puppy");
  byText("h2", "Facts").parentElement.querySelector("form")
    .dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor("fact listed", () => byText(".fact", "puppy"));
  console.log("✓ fact added");

  // --- family via membership combobox create ---
  const famInput = q('.combo input[placeholder="add to family…"]');
  focus(famInput); type(famInput, "Smiths");
  pointer(await waitFor("create family row", () => famInput.closest(".combo").querySelector(".combo-list button.create")));
  await waitFor("family chip", () => byText(".chip a", "Smiths"));
  console.log("✓ family created + membership added from person page");

  // --- duplicate-prevention: typing exact name of existing family again ---
  // remove membership first so it appears filtered-out scenario is not hit;
  // instead directly verify resolveOrCreate reuses: create second person page.
  window.location.hash = "#/";
  await waitFor("home shows Alice", () => byText("a.card h3", "Alice"));
  q('button[data-add="persons"]').click();
  const form2 = await waitFor("create form 2", () => q("form.card"));
  type(form2.querySelector("input"), "Bob");
  form2.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor("bob view", () => byText("h1", "Bob"));
  const famInput2 = await waitFor("fam input", () => q('.combo input[placeholder="add to family…"]'));
  focus(famInput2); type(famInput2, "smiths"); // different case, existing family
  // suggestion should appear (Bob is not a member) — pick the suggestion
  pointer(await waitFor("smiths suggestion", () => suggestion("Smiths")));
  await waitFor("bob in smiths", () => byText(".chip a", "Smiths"));
  const fams = await (await fetch(BASE + "/api/families")).json();
  if (fams.length !== 1) throw new Error("duplicate family created: " + JSON.stringify(fams));
  console.log("✓ existing family reused, no duplicate");

  // --- value vocabulary shared across people ---
  const attrInput2 = q('.combo input[placeholder^="attribute"]');
  focus(attrInput2); type(attrInput2, "likes");
  await sleep(250);
  const valInput2 = q('.combo input[placeholder="value…"]');
  focus(valInput2); type(valInput2, "tom");
  await waitFor("tomatoes suggested for Bob", () => suggestion("tomatoes"));
  console.log("✓ 'tomatoes' (entered for Alice) suggested while editing Bob");
  pointer(suggestion("tomatoes"));
  await waitFor("bob tomato chip", () => byText(".chip", "tomatoes"));

  // --- family single-page view ---
  window.location.hash = "#/family/1";
  await waitFor("glance", () => byText("h2", "Members at a glance"));
  if (!byText(".card", "shellfish")) throw new Error("member attrs missing in glance");
  console.log("✓ family page shows members' data at a glance");

  // --- meal plan report ---
  window.location.hash = "#/plan?family=1";
  await waitFor("avoid section", () => q(".report-section.avoid"));
  const avoidTxt = q(".report-section.avoid").textContent;
  const serveTxt = q(".report-section.serve").textContent;
  if (!avoidTxt.includes("shellfish")) throw new Error("shellfish not in avoid");
  if (!serveTxt.includes("tomatoes")) throw new Error("tomatoes not in serve");
  console.log("✓ meal plan: avoid=shellfish, serve=tomatoes (×2)");

  // --- Enter key: exact match picked, not superstring ---
  window.location.hash = "#/person/1";
  await waitFor("alice again", () => byText("h1", "Alice"));
  const ai = q('.combo input[placeholder^="attribute"]');
  focus(ai); type(ai, "likes");
  await sleep(250);
  const vi = q('.combo input[placeholder="value…"]');
  focus(vi); type(vi, "tomatoes");
  await sleep(300); // let suggestions land so lastQuery matches
  vi.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await sleep(400);
  const vals = await (await fetch(BASE + "/api/values?attribute=likes")).json();
  if (vals.length !== 1) throw new Error("Enter created duplicate value: " + JSON.stringify(vals));
  console.log("✓ Enter reuses exact vocabulary match, no duplicate");

  if (errors.length) {
    console.error("ERRORS:", errors);
    process.exit(1);
  }
  console.log("\nALL UI FLOWS OK (jsdom)");
  process.exit(0);
}

main().catch((e) => { console.error("FAIL:", e.message); if (errors.length) console.error("errors:", errors); process.exit(1); });
