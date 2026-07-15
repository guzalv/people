"use strict";

/* ---------- helpers ---------- */

const $view = document.getElementById("view");

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    toast(`Error: ${detail}`);
    throw new Error(detail);
  }
  return res.json();
}
const GET = (p) => api("GET", p);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// Resolve "create X" from a membership combobox: the suggestion list filters
// out entities that are already members, so an exact name match may exist
// even when the user was offered "Add" — reuse it instead of duplicating.
async function resolveOrCreate(kind, item) {
  if (!item.isNew) return item.id;
  const all = await GET(`/api/${kind}?q=${encodeURIComponent(item.label)}`);
  const hit = all.find((e) => e.name.toLowerCase() === item.label.toLowerCase());
  if (hit) return hit.id;
  return (await api("POST", `/api/${kind}`, { name: item.label })).id;
}

let toastTimer;
function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) { t = el(`<div id="toast"></div>`); document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

function fmtDate(s) {
  if (!s) return "";
  // SQLite datetime('now') is UTC; render as the local date.
  const d = new Date(s.replace(" ", "T") + "Z");
  return isNaN(d) ? s.slice(0, 10) : d.toLocaleDateString();
}

function debounce(fn, ms) {
  let h;
  return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}

/* ---------- combobox: filter-as-you-type + create-if-missing ---------- */
/*
 * suggest(q) -> Promise<[{id, label, hint?}]>
 * onPick({id?, label, isNew}) — isNew when the user chose "Add ...".
 * The input clears after pick (create flows) unless keepValue is set.
 */
function combobox({ placeholder, suggest, onPick, keepValue = false, allowCreate = true }) {
  const root = el(`<div class="combo">
    <input type="text" placeholder="${esc(placeholder)}" autocomplete="off">
  </div>`);
  const input = root.querySelector("input");
  let list = null;
  let lastItems = [];   // suggestions currently shown
  let lastQuery = null; // the query they were fetched for

  const close = () => { if (list) { list.remove(); list = null; } };

  async function open() {
    const q = input.value.trim();
    const items = await suggest(q);
    if (input.value.trim() !== q) return; // stale response, newer fetch coming
    lastItems = items;
    lastQuery = q;
    close();
    if (document.activeElement !== input) return; // blurred while fetching
    list = el(`<div class="combo-list"></div>`);
    for (const it of items.slice(0, 12)) {
      const b = el(`<button type="button">${esc(it.label)}
        ${it.hint ? `<span class="hint">${esc(it.hint)}</span>` : ""}</button>`);
      b.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        pick({ ...it, isNew: false });
      });
      list.appendChild(b);
    }
    const exact = items.some((it) => it.label.toLowerCase() === q.toLowerCase());
    if (allowCreate && q && !exact) {
      const b = el(`<button type="button" class="create">＋ Add “${esc(q)}”</button>`);
      b.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        pick({ label: q, isNew: true });
      });
      list.appendChild(b);
    }
    if (!list.children.length) { close(); return; }
    root.appendChild(list);
  }

  function pick(item) {
    close();
    input.value = keepValue ? item.label : "";
    onPick(item);
  }

  input.addEventListener("input", debounce(open, 150));
  input.addEventListener("focus", open);
  input.addEventListener("blur", () => setTimeout(close, 150));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) return;
      // Only trust an exact match, and only if the list is for this query —
      // never blind-pick the top suggestion (it may be a stale or superstring
      // match, e.g. "teabread" ranked above the typed "tea").
      const exact = lastQuery === q &&
        lastItems.find((it) => it.label.toLowerCase() === q.toLowerCase());
      if (exact) pick({ ...exact, isNew: false });
      else if (allowCreate) pick({ label: q, isNew: true });
    }
    if (e.key === "Escape") close();
  });

  root.focus = () => input.focus();
  root.input = input;
  return root;
}

/* ---------- attribute + facts sections (shared by person & family) ---------- */

// The food attributes are fixed: always visible in their own section, and the
// only ones the meal plan reads. Free-form attributes never affect reports.
const FOOD_ATTRS = [
  { name: "likes",    label: "Likes",     cls: "like"  },
  { name: "dislikes", label: "Dislikes",  cls: "avoid" },
  { name: "allergy",  label: "Allergies", cls: "avoid" },
  { name: "diet",     label: "Diet",      cls: "diet"  },
];
const FOOD_NAMES = new Set(FOOD_ATTRS.map((f) => f.name));

// Last attribute used in the add row, kept across the full re-render that
// follows each mutation so adding several values in a row stays frictionless.
let lastAttr = null;

function attributeChip(item, cls, reload) {
  const chip = el(`<span class="chip ${cls}">
    <span class="val" title="tap to edit note">${esc(item.value)}${item.note ? ` <span class="note">(${esc(item.note)})</span>` : ""}</span>
    <button type="button" title="remove">×</button>
  </span>`);
  chip.querySelector(".val").addEventListener("click", async () => {
    const note = prompt(`Note for “${item.value}”`, item.note);
    if (note === null) return; // cancelled
    await api("PATCH", `/api/entity-attributes/${item.id}`, { note: note.trim() });
    reload();
  });
  chip.querySelector("button").addEventListener("click", async () => {
    await api("DELETE", `/api/entity-attributes/${item.id}`);
    reload();
  });
  return chip;
}

function valueCombobox(attrName, entity, kind, reload, placeholder = "add…") {
  return combobox({
    placeholder,
    suggest: (q) =>
      GET(`/api/values?attribute=${encodeURIComponent(attrName)}&q=${encodeURIComponent(q)}`)
        .then((vs) => vs.map((v) => ({ label: v.value, hint: `×${v.uses}` }))),
    onPick: async (item) => {
      await api("POST", `/api/${kind}/${entity.id}/attributes`,
        { attribute: attrName, value: item.label });
      reload();
    },
  });
}

function foodSection(entity, kind, reload) {
  const root = el(`<section>
    <h2>Food <span class="hint">— feeds the meal plan</span></h2>
    <div class="card"></div>
  </section>`);
  const card = root.querySelector(".card");
  for (const f of FOOD_ATTRS) {
    const row = el(`<div class="food-row">
      <span class="label">${esc(f.label)}</span>
      <span class="chips"></span>
      <span class="add"></span>
    </div>`);
    const chips = row.querySelector(".chips");
    for (const item of entity.attributes.filter((a) => a.attribute === f.name)) {
      chips.appendChild(attributeChip(item, f.cls, reload));
    }
    row.querySelector(".add").appendChild(valueCombobox(f.name, entity, kind, reload));
    card.appendChild(row);
  }
  return root;
}

function attributesSection(entity, kind, reload) {
  // kind: "persons" | "families" — free-form attributes only (food is above)
  const root = el(`<section><h2>Other attributes</h2><div class="card"></div></section>`);
  const card = root.querySelector(".card");

  // existing values grouped by attribute
  const groups = new Map();
  for (const a of entity.attributes) {
    if (FOOD_NAMES.has(a.attribute.toLowerCase())) continue;
    if (!groups.has(a.attribute)) groups.set(a.attribute, []);
    groups.get(a.attribute).push(a);
  }
  for (const [name, items] of groups) {
    const grp = el(`<div class="attr-group">
      <div class="attr-head"><span class="name">${esc(name)}</span></div>
      <div class="chips"></div>
    </div>`);
    const chips = grp.querySelector(".chips");
    for (const item of items) chips.appendChild(attributeChip(item, "", reload));
    card.appendChild(grp);
  }
  if (!groups.size) card.appendChild(el(`<div class="empty">Nothing yet</div>`));

  // add row: attribute combobox -> value combobox (scoped to the attribute)
  const addRow = el(`<div class="row mt"></div>`);
  let chosenAttr = lastAttr;

  const valueBox = combobox({
    placeholder: "value…",
    suggest: (q) => chosenAttr
      ? GET(`/api/values?attribute=${encodeURIComponent(chosenAttr)}&q=${encodeURIComponent(q)}`)
          .then((vs) => vs.map((v) => ({ label: v.value, hint: `×${v.uses}` })))
      : Promise.resolve([]),
    onPick: async (item) => {
      if (!chosenAttr) { toast("Pick an attribute first"); return; }
      await api("POST", `/api/${kind}/${entity.id}/attributes`,
        { attribute: chosenAttr, value: item.label });
      lastAttr = chosenAttr;
      reload();
    },
  });

  const attrBox = combobox({
    placeholder: "attribute (hobby, birthday…)",
    keepValue: true,
    suggest: (q) => GET(`/api/attributes?q=${encodeURIComponent(q)}`)
      .then((as) => as
        .filter((a) => !FOOD_NAMES.has(a.name.toLowerCase()))
        .map((a) => ({ label: a.name }))),
    onPick: (item) => { chosenAttr = item.label; valueBox.focus(); },
  });
  attrBox.input.addEventListener("input", () => { chosenAttr = attrBox.input.value.trim() || null; });
  if (lastAttr) attrBox.input.value = lastAttr;

  addRow.appendChild(el(`<div class="grow"></div>`)).appendChild(attrBox);
  addRow.appendChild(el(`<div class="grow"></div>`)).appendChild(valueBox);
  card.appendChild(addRow);
  return root;
}

function factsSection(entity, kind, reload) {
  const root = el(`<section><h2>Facts</h2><div class="card"></div></section>`);
  const card = root.querySelector(".card");
  for (const f of entity.facts) {
    const row = el(`<div class="fact">
      <span class="when">${esc(fmtDate(f.created_at))}</span>
      <span class="text">${esc(f.text)}</span>
      <button type="button" class="icon" title="delete">×</button>
    </div>`);
    row.querySelector("button").addEventListener("click", async () => {
      await api("DELETE", `/api/facts/${f.id}`);
      reload();
    });
    card.appendChild(row);
  }
  if (!entity.facts.length) card.appendChild(el(`<div class="empty">Nothing yet</div>`));

  const form = el(`<form class="row mt">
    <input type="text" class="grow" placeholder="something they mentioned…">
    <button>Add</button>
  </form>`);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = form.querySelector("input").value.trim();
    if (!text) return;
    await api("POST", `/api/${kind}/${entity.id}/facts`, { text });
    reload();
  });
  card.appendChild(form);
  return root;
}

function editableHeader(entity, kind, reload, extraSub = "") {
  const root = el(`<section>
    <div class="spread">
      <h1>${esc(entity.name)}</h1>
      <span>
        <button type="button" class="ghost" data-act="edit">Edit</button>
        <button type="button" class="danger" data-act="del">Delete</button>
      </span>
    </div>
    ${extraSub}
    <div class="sub muted" data-notes>${esc(entity.notes)}</div>
  </section>`);
  root.querySelector('[data-act="del"]').addEventListener("click", async () => {
    if (!confirm(`Delete ${entity.name}? This removes their attributes and facts.`)) return;
    await api("DELETE", `/api/${kind}/${entity.id}`);
    location.hash = "#/";
  });
  root.querySelector('[data-act="edit"]').addEventListener("click", () => {
    const form = el(`<form class="card">
      <input type="text" value="${esc(entity.name)}" required>
      <textarea placeholder="notes">${esc(entity.notes)}</textarea>
      <div class="row mt"><button>Save</button>
      <button type="button" class="ghost" data-act="cancel">Cancel</button></div>
    </form>`);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await api("PUT", `/api/${kind}/${entity.id}`, {
        name: form.querySelector("input").value.trim(),
        notes: form.querySelector("textarea").value.trim(),
      });
      reload();
    });
    form.querySelector('[data-act="cancel"]').addEventListener("click", reload);
    root.replaceChildren(form);
  });
  return root;
}

/* ---------- views ---------- */

async function homeView() {
  const [persons, families] = await Promise.all([GET("/api/persons"), GET("/api/families")]);
  const root = el(`<div>
    <input type="search" id="search" placeholder="Search people and families…">
    <h2>Families</h2><div data-list="families"></div>
    <div class="row"><button class="ghost" data-add="families">＋ New family</button></div>
    <h2>People</h2><div data-list="persons"></div>
    <div class="row"><button class="ghost" data-add="persons">＋ New person</button></div>
  </div>`);

  function render(q = "") {
    const match = (s) => s.toLowerCase().includes(q.toLowerCase());
    const fl = root.querySelector('[data-list="families"]');
    fl.replaceChildren(...families.filter((f) => match(f.name)).map((f) =>
      el(`<a class="card" href="#/family/${f.id}">
        <h3>${esc(f.name)}</h3>
        <div class="sub">${f.member_count} member${f.member_count === 1 ? "" : "s"}${f.notes ? " · " + esc(f.notes) : ""}</div>
      </a>`)));
    if (!fl.children.length) fl.appendChild(el(`<div class="empty">No families</div>`));
    const pl = root.querySelector('[data-list="persons"]');
    pl.replaceChildren(...persons.filter((p) => match(p.name)).map((p) =>
      el(`<a class="card" href="#/person/${p.id}">
        <h3>${esc(p.name)}</h3>
        <div class="sub">${p.families ? esc(p.families) : ""}${p.families && p.notes ? " · " : ""}${esc(p.notes || "")}</div>
      </a>`)));
    if (!pl.children.length) pl.appendChild(el(`<div class="empty">No people</div>`));
  }
  render();
  root.querySelector("#search").addEventListener("input", (e) => render(e.target.value.trim()));

  for (const btn of root.querySelectorAll("[data-add]")) {
    const kind = btn.dataset.add;
    btn.addEventListener("click", () => {
      const form = el(`<form class="card row">
        <input type="text" class="grow" placeholder="name" required>
        <button>Create</button>
      </form>`);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = form.querySelector("input").value.trim();
        if (!name) return;
        const { id } = await api("POST", `/api/${kind}`, { name });
        location.hash = kind === "persons" ? `#/person/${id}` : `#/family/${id}`;
      });
      btn.replaceWith(form);
      form.querySelector("input").focus();
    });
  }
  return root;
}

async function personView(id) {
  const p = await GET(`/api/persons/${id}`);
  const reload = () => route();
  const root = el(`<div></div>`);
  root.appendChild(editableHeader(p, "persons", reload));

  // families the person belongs to
  const famSec = el(`<section><h2>Families</h2><div class="card">
    <div class="chips"></div><div class="mt" data-add></div>
  </div></section>`);
  const chips = famSec.querySelector(".chips");
  for (const f of p.families) {
    const chip = el(`<span class="chip"><a href="#/family/${f.id}">${esc(f.name)}</a>
      <button type="button" title="remove">×</button></span>`);
    chip.querySelector("button").addEventListener("click", async () => {
      await api("DELETE", `/api/families/${f.id}/members/${p.id}`);
      reload();
    });
    chips.appendChild(chip);
  }
  famSec.querySelector("[data-add]").appendChild(combobox({
    placeholder: "add to family…",
    suggest: async (q) => {
      const fams = await GET(`/api/families?q=${encodeURIComponent(q)}`);
      const mine = new Set(p.families.map((f) => f.id));
      return fams.filter((f) => !mine.has(f.id)).map((f) => ({ id: f.id, label: f.name }));
    },
    onPick: async (item) => {
      const fid = await resolveOrCreate("families", item);
      await api("PUT", `/api/families/${fid}/members/${p.id}`);
      reload();
    },
  }));
  root.appendChild(famSec);

  root.appendChild(foodSection(p, "persons", reload));
  root.appendChild(attributesSection(p, "persons", reload));
  root.appendChild(factsSection(p, "persons", reload));
  return root;
}

function memberGlance(m) {
  const bits = [];
  for (const a of m.attributes) {
    const cls = a.polarity !== "neutral" ? a.polarity : "";
    bits.push(`<span class="chip ${cls}">${esc(a.attribute)}: ${esc(a.value)}</span>`);
  }
  const facts = m.facts.slice(0, 3).map((f) =>
    `<div class="fact"><span class="when">${esc(fmtDate(f.created_at))}</span>
     <span class="text">${esc(f.text)}</span></div>`).join("");
  return el(`<div class="card">
    <div class="spread"><h3><a href="#/person/${m.id}">${esc(m.name)}</a></h3></div>
    ${m.notes ? `<div class="sub">${esc(m.notes)}</div>` : ""}
    ${bits.length ? `<div class="chips mt">${bits.join("")}</div>` : ""}
    ${facts}
    ${!bits.length && !facts ? `<div class="sub muted">Nothing recorded yet</div>` : ""}
  </div>`);
}

async function familyView(id) {
  const f = await GET(`/api/families/${id}`);
  const reload = () => route();
  const root = el(`<div></div>`);
  root.appendChild(editableHeader(f, "families", reload));

  // members
  const memSec = el(`<section><h2>Members</h2><div class="card">
    <div class="chips"></div><div class="mt" data-add></div>
  </div></section>`);
  const chips = memSec.querySelector(".chips");
  for (const m of f.members) {
    const chip = el(`<span class="chip"><a href="#/person/${m.id}">${esc(m.name)}</a>
      <button type="button" title="remove">×</button></span>`);
    chip.querySelector("button").addEventListener("click", async () => {
      await api("DELETE", `/api/families/${f.id}/members/${m.id}`);
      reload();
    });
    chips.appendChild(chip);
  }
  memSec.querySelector("[data-add]").appendChild(combobox({
    placeholder: "add person…",
    suggest: async (q) => {
      const ps = await GET(`/api/persons?q=${encodeURIComponent(q)}`);
      const mine = new Set(f.members.map((m) => m.id));
      return ps.filter((x) => !mine.has(x.id)).map((x) => ({ id: x.id, label: x.name }));
    },
    onPick: async (item) => {
      const pid = await resolveOrCreate("persons", item);
      await api("PUT", `/api/families/${f.id}/members/${pid}`);
      reload();
    },
  }));
  root.appendChild(memSec);

  root.appendChild(foodSection(f, "families", reload));
  root.appendChild(attributesSection(f, "families", reload));
  root.appendChild(factsSection(f, "families", reload));

  // everything about the members, one page
  const glance = el(`<section><h2>Members at a glance</h2></section>`);
  for (const m of f.members) glance.appendChild(memberGlance(m));
  if (!f.members.length) glance.appendChild(el(`<div class="empty">No members yet</div>`));
  root.appendChild(glance);

  const planBtn = el(`<div class="row mt"><button class="ghost">🍽 Meal plan for this family</button></div>`);
  planBtn.querySelector("button").addEventListener("click", () => {
    location.hash = `#/plan?family=${f.id}`;
  });
  root.appendChild(planBtn);
  return root;
}

async function planView(params) {
  const [persons, families] = await Promise.all([GET("/api/persons"), GET("/api/families")]);
  const preFamily = params.get("family");
  const root = el(`<div>
    <h1>Meal plan</h1>
    <p class="muted small">Pick who's coming; the report shows what to avoid and what they'd enjoy.</p>
    <h2>Families</h2><div class="card" data-fams></div>
    <h2>People</h2><div class="card" data-ppl></div>
    <div data-report class="mt"></div>
  </div>`);

  const famBox = root.querySelector("[data-fams]");
  const pplBox = root.querySelector("[data-ppl]");
  for (const f of families) {
    famBox.appendChild(el(`<label class="check">
      <input type="checkbox" data-family="${f.id}" ${String(f.id) === preFamily ? "checked" : ""}>
      <span>${esc(f.name)} <span class="muted small">(${f.member_count})</span></span>
    </label>`));
  }
  if (!families.length) famBox.appendChild(el(`<div class="empty">No families</div>`));
  for (const p of persons) {
    pplBox.appendChild(el(`<label class="check">
      <input type="checkbox" data-person="${p.id}">
      <span>${esc(p.name)}${p.families ? ` <span class="muted small">(${esc(p.families)})</span>` : ""}</span>
    </label>`));
  }
  if (!persons.length) pplBox.appendChild(el(`<div class="empty">No people</div>`));

  const out = root.querySelector("[data-report]");
  let seq = 0; // drop out-of-order report responses
  async function refresh() {
    const my = ++seq;
    const person_ids = [...root.querySelectorAll("[data-person]:checked")].map((c) => +c.dataset.person);
    const family_ids = [...root.querySelectorAll("[data-family]:checked")].map((c) => +c.dataset.family);
    if (!person_ids.length && !family_ids.length) { out.replaceChildren(); return; }
    const rep = await api("POST", "/api/report/food", { person_ids, family_ids });
    if (my !== seq) return; // a newer selection superseded this request
    const who = (list) => list.map((w) =>
      `${esc(w.person)} <span class="muted">(${esc(w.reason)}${w.via_family ? `, via ${esc(w.via_family)}` : ""})</span>`).join(", ");
    out.replaceChildren(el(`<div>
      <h2>For: ${rep.people.map((p) => esc(p.name)).join(", ") || "—"}</h2>
      <div class="card report-section avoid">
        <h3>🚫 Avoid</h3>
        ${rep.avoid.map((e) => `<div class="report-item">
            <div class="val">${esc(e.value)}</div>
            <div class="why">${who(e.who)}</div>
            ${e.conflicts.length ? `<div class="conflict">⚠ but liked by ${e.conflicts.map((c) => esc(c.person)).join(", ")}</div>` : ""}
          </div>`).join("") || `<div class="empty">Nothing to avoid</div>`}
      </div>
      ${rep.diets.length ? `<div class="card report-section diet">
        <h3>🥗 Diets to accommodate</h3>
        ${rep.diets.map((e) => `<div class="report-item">
            <div class="val">${esc(e.value)}</div>
            <div class="why">${who(e.who)}</div>
          </div>`).join("")}
      </div>` : ""}
      <div class="card report-section serve">
        <h3>✓ Good choices</h3>
        ${rep.serve.map((e) => `<div class="report-item">
            <div class="val">${esc(e.value)} <span class="muted small">×${e.count}</span></div>
            <div class="why">${who(e.who)}</div>
          </div>`).join("") || `<div class="empty">No known favourites</div>`}
      </div>
    </div>`));
  }
  root.addEventListener("change", refresh);
  if (preFamily) refresh();
  return root;
}

/* ---------- router ---------- */

async function route() {
  const hash = location.hash || "#/";
  const [path, query] = hash.slice(1).split("?");
  const params = new URLSearchParams(query || "");
  const parts = path.split("/").filter(Boolean);

  let view, nav = "home";
  try {
    if (!parts.length) view = await homeView();
    else if (parts[0] === "person" && parts[1]) view = await personView(+parts[1]);
    else if (parts[0] === "family" && parts[1]) view = await familyView(+parts[1]);
    else if (parts[0] === "plan") { view = await planView(params); nav = "plan"; }
    else view = el(`<div class="empty">Not found</div>`);
  } catch (e) {
    view = el(`<div class="empty">Failed to load — ${esc(e.message)}</div>`);
  }
  for (const a of document.querySelectorAll("[data-nav]"))
    a.classList.toggle("active", a.dataset.nav === nav);
  $view.replaceChildren(view);
}

window.addEventListener("hashchange", route);
route();
