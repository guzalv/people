// Drive the SPA in jsdom against the live server: exercise routing, the
// autocomplete-create combobox, the fixed Food section, free-form attributes,
// facts, membership, and the meal-plan report.
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
  // find a fixed food row (Likes / Dislikes / Allergies / Diet) — re-query fresh
  // from the document each time since full-page reloads replace the DOM.
  const foodRow = (label) =>
    [...document.querySelectorAll(".food-row")].find((r) => r.querySelector(".label").textContent === label);

  // --- home renders (fresh DB: empty) ---
  await waitFor("home empty state", () => byText(".empty", "No people"));
  console.log("✓ home renders");

  // --- create a person through the UI ---
  q('button[data-add="persons"]').click();
  const form = await waitFor("create form", () => q("form.card"));
  type(form.querySelector("input"), "Alice");
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor("person view", () => byText("h1", "Alice"));
  const aliceId = window.location.hash.match(/\d+/)[0];
  console.log("✓ person created via UI, routed to #" + window.location.hash);

  // --- Food section: Likes row, create "tomatoes" ---
  let likesRow = await waitFor("likes row", () => foodRow("Likes"));
  let likesInput = likesRow.querySelector(".add input");
  focus(likesInput); type(likesInput, "tomatoes");
  let createBtn = await waitFor("likes create btn", () =>
    likesInput.closest(".combo").querySelector(".combo-list button.create"));
  pointer(createBtn);
  await waitFor("tomatoes chip.like", () => {
    const row = foodRow("Likes");
    return row && [...row.querySelectorAll(".chip.like")].some((c) => c.textContent.includes("tomatoes"));
  });
  console.log("✓ Food: Likes → tomatoes added (chip.like)");

  // --- Food section: Allergies row, create "shellfish" ---
  let allergiesRow = await waitFor("allergies row", () => foodRow("Allergies"));
  let allergiesInput = allergiesRow.querySelector(".add input");
  focus(allergiesInput); type(allergiesInput, "shellfish");
  createBtn = await waitFor("allergies create btn", () =>
    allergiesInput.closest(".combo").querySelector(".combo-list button.create"));
  pointer(createBtn);
  await waitFor("shellfish chip.avoid", () => {
    const row = foodRow("Allergies");
    return row && [...row.querySelectorAll(".chip.avoid")].some((c) => c.textContent.includes("shellfish"));
  });
  console.log("✓ Food: Allergies → shellfish added (chip.avoid)");

  // --- note editing via chip tap (prompt stub) ---
  const chipVal = byText(".chip .val", "shellfish");
  chipVal.click();
  await waitFor("note shown", () => byText(".chip .note", "epipen"));
  console.log("✓ note edited via chip tap");

  // --- Other attributes: attribute "hobby", value "chess" ---
  let attrInput = await waitFor("attr input", () => q('.combo input[placeholder^="attribute"]'));
  focus(attrInput); type(attrInput, "hobby");
  let valInput = await waitFor("value input", () => q('.combo input[placeholder="value…"]'));
  focus(valInput); type(valInput, "chess");
  createBtn = await waitFor("chess create btn", () =>
    valInput.closest(".combo").querySelector(".combo-list button.create"));
  pointer(createBtn);
  const chessChip = await waitFor("chess chip", () => byText(".chip", "chess"));
  if (chessChip.classList.length !== 1 || !chessChip.classList.contains("chip"))
    throw new Error("expected plain chip for free-form attribute, got class=" + chessChip.className);
  console.log("✓ Other attributes: hobby → chess added (plain chip)");

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
  window.location.hash = "#/";
  await waitFor("home shows Alice", () => byText("a.card h3", "Alice"));
  q('button[data-add="persons"]').click();
  const form2 = await waitFor("create form 2", () => q("form.card"));
  type(form2.querySelector("input"), "Bob");
  form2.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor("bob view", () => byText("h1", "Bob"));
  const bobId = window.location.hash.match(/\d+/)[0];
  const famInput2 = await waitFor("fam input", () => q('.combo input[placeholder="add to family…"]'));
  focus(famInput2); type(famInput2, "smiths"); // different case, existing family
  // suggestion should appear (Bob is not a member) — pick the suggestion
  pointer(await waitFor("smiths suggestion", () => suggestion("Smiths")));
  await waitFor("bob in smiths", () => byText(".chip a", "Smiths"));
  const fams = await (await fetch(BASE + "/api/families")).json();
  if (fams.length !== 1) throw new Error("duplicate family created: " + JSON.stringify(fams));
  console.log("✓ existing family reused, no duplicate");

  // --- cross-person suggestion: Bob's Likes row suggests "tomatoes" (Alice's) ---
  const bobLikesRow = await waitFor("bob likes row", () => foodRow("Likes"));
  const bobLikesInput = bobLikesRow.querySelector(".add input");
  focus(bobLikesInput); type(bobLikesInput, "tom");
  const tomatoesSuggestion = await waitFor("tomatoes suggestion for Bob", () => suggestion("tomatoes"));
  pointer(tomatoesSuggestion);
  await waitFor("bob tomatoes chip", () => {
    const row = foodRow("Likes");
    return row && [...row.querySelectorAll(".chip.like")].some((c) => c.textContent.includes("tomatoes"));
  });
  console.log("✓ 'tomatoes' (entered for Alice) suggested + picked while editing Bob");

  // --- family single-page view ---
  window.location.hash = "#/family/1";
  await waitFor("glance", () => byText("h2", "Members at a glance"));
  if (!byText(".card", "shellfish")) throw new Error("member attrs missing in glance");
  console.log("✓ family page shows members' data at a glance");

  // --- meal plan report ---
  window.location.hash = "#/plan?family=1";
  await waitFor("avoid section", () => q(".report-section.avoid"));
  let avoidTxt = q(".report-section.avoid").textContent;
  let serveTxt = q(".report-section.serve").textContent;
  if (!avoidTxt.includes("shellfish")) throw new Error("shellfish not in avoid");
  if (!serveTxt.includes("tomatoes")) throw new Error("tomatoes not in serve");
  console.log("✓ meal plan: avoid=shellfish, serve=tomatoes");

  // --- Diet flow: Bob's Diet row → "vegetarian", meal plan shows diet section ---
  window.location.hash = "#/person/" + bobId;
  await waitFor("bob page again", () => byText("h1", "Bob"));
  const dietRow = await waitFor("diet row", () => foodRow("Diet"));
  const dietInput = dietRow.querySelector(".add input");
  focus(dietInput); type(dietInput, "vegetarian");
  createBtn = await waitFor("diet create btn", () =>
    dietInput.closest(".combo").querySelector(".combo-list button.create"));
  pointer(createBtn);
  await waitFor("vegetarian chip.diet", () => {
    const row = foodRow("Diet");
    return row && [...row.querySelectorAll(".chip.diet")].some((c) => c.textContent.includes("vegetarian"));
  });
  console.log("✓ Food: Diet → vegetarian added (chip.diet) for Bob");

  window.location.hash = "#/plan?family=1";
  await waitFor("diet section", () => q(".report-section.diet"));
  const dietTxt = q(".report-section.diet").textContent;
  if (!dietTxt.includes("vegetarian")) throw new Error("vegetarian not in diet section");
  console.log("✓ meal plan: diet section shows vegetarian");

  // --- Enter key: exact match picked, not superstring, no duplicate value ---
  window.location.hash = "#/person/" + aliceId;
  await waitFor("alice again", () => byText("h1", "Alice"));
  const likesRow2 = await waitFor("alice likes row", () => foodRow("Likes"));
  const li = likesRow2.querySelector(".add input");
  focus(li); type(li, "tomatoes");
  await sleep(300); // let suggestions land so lastQuery matches
  li.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
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
