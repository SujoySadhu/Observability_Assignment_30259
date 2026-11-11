// ShopLite storefront: a single-page app in plain JavaScript (no build step).
// Routing uses the URL hash (#/products, #/cart, ...), so nginx only ever serves index.html.

// ============================================================================
// Helpers
// ============================================================================
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");
const money = (cents) => `$${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const CATEGORY = {
  laptops: { label: "Laptops", emoji: "💻" },
  phones: { label: "Phones", emoji: "📱" },
  audio: { label: "Audio", emoji: "🎧" },
  accessories: { label: "Accessories", emoji: "🔌" },
  gaming: { label: "Gaming", emoji: "🎮" },
  "smart-home": { label: "Smart Home", emoji: "🏠" },
};
const catLabel = (c) => (CATEGORY[c] || { label: c }).label;
const catEmoji = (c) => (CATEGORY[c] || { emoji: "📦" }).emoji;

const store = {
  get(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};

const state = {
  token: store.get("shoplite_token"),
  user: store.get("shoplite_user"),
  coupon: null,
  categories: [],
};

function toast(message, type = "", linkHref = "", linkText = "") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = esc(message) + (linkHref ? `<a href="${linkHref}">${esc(linkText)}</a>` : "");
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 4000);
}

const loading = (text = "Loading…") => `<div class="loading"><div class="spinner"></div>${esc(text)}</div>`;

function stars(rating) {
  const r = Math.round(Number(rating));
  return `<span class="stars">${"★".repeat(r)}${"☆".repeat(5 - r)}<span>${Number(rating).toFixed(1)}</span></span>`;
}

function stockText(stock) {
  if (stock === 0) return `<span class="stock out">Out of stock</span>`;
  if (stock < 20) return `<span class="stock low">Only ${stock} left</span>`;
  return `<span class="stock">In stock</span>`;
}

// ============================================================================
// API client
// ============================================================================
async function api(method, path, body) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    return { ok: false, status: 0, data: null, message: "Can't reach the shop. Check your connection." };
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (res.status === 401 && state.token) {
    setSession(null, null);  // token expired or revoked
  }
  const detail = data && data.detail;
  let message = (detail && detail.message) || "";
  if (!res.ok && !message) {
    message = res.status >= 500 ? "Something went wrong on our side. Please try again." : "Request failed.";
  }
  return { ok: res.ok, status: res.status, data, message };
}

function setSession(token, user) {
  state.token = token;
  state.user = user;
  if (token) { store.set("shoplite_token", token); store.set("shoplite_user", user); }
  else { store.del("shoplite_token"); store.del("shoplite_user"); state.coupon = null; }
  renderAccount();
  refreshCartCount();
}

async function refreshCartCount() {
  if (!state.token) { $("#cart-count").textContent = "0"; return; }
  const res = await api("GET", "/api/cart");
  if (res.ok) $("#cart-count").textContent = res.data.totals.units;
}

async function addToCart(productId, quantity = 1, goToCart = false) {
  if (!state.token) {
    toast("Please log in to add items to your cart.");
    location.hash = `#/login?next=${encodeURIComponent(location.hash.slice(1) || "/")}`;
    return;
  }
  const res = await api("POST", "/api/cart/items", { product_id: productId, quantity });
  if (!res.ok) { toast(res.message, "bad"); return; }
  $("#cart-count").textContent = res.data.totals.units;
  if (goToCart) location.hash = "#/cart";
  else toast("Added to your cart.", "", "#/cart", "View cart");
}

// ============================================================================
// Layout pieces
// ============================================================================
function renderAccount() {
  $("#account").innerHTML = state.user
    ? `<span>Hi, ${esc(state.user.name.split(" ")[0])}</span><a href="#/orders">My orders</a><button class="link" id="logout">Log out</button>`
    : `<a href="#/login">Log in</a><a href="#/register">Create account</a>`;
  const btn = $("#logout");
  if (btn) btn.addEventListener("click", async () => {
    await api("POST", "/api/auth/logout");
    setSession(null, null);
    toast("You have been logged out.");
    location.hash = "#/";
  });
}

function renderCategoryNav(active) {
  $("#cats").innerHTML = `<a href="#/products" class="${active === "all" ? "active" : ""}">All products</a>` +
    state.categories.map((c) => `<a href="#/products?category=${c.name}" class="${active === c.name ? "active" : ""}">${catEmoji(c.name)} ${esc(catLabel(c.name))}</a>`).join("");
}

function productCard(p) {
  return `
    <div class="product">
      <a href="#/product/${p.id}" class="thumb cat-${esc(p.category)}">${catEmoji(p.category)}</a>
      <div class="body">
        <a href="#/product/${p.id}" class="name">${esc(p.name)}</a>
        ${stars(p.rating)}
        <span class="price">${money(p.price_cents)}</span>
        ${stockText(p.stock)}
        <button data-add="${p.id}" ${p.stock === 0 ? "disabled" : ""}>Add to cart</button>
      </div>
    </div>`;
}

// One click handler for every "Add to cart" button on any page.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-add]");
  if (btn) addToCart(Number(btn.dataset.add));
});

// ============================================================================
// Views
// ============================================================================
async function viewHome() {
  renderCategoryNav("");
  const res = await api("GET", "/api/products?sort=rating");
  view.innerHTML = `
    <section class="hero">
      <div>
        <h1>New season tech is here</h1>
        <p>Laptops, phones, audio and smart home gear from top brands. Free shipping on orders over $50.</p>
        <button onclick="location.hash='#/products'">Shop all products</button>
      </div>
      <div class="promo">New customer? Use code<b>WELCOME10</b>for 10% off</div>
    </section>
    <h2>Shop by category</h2>
    <div class="tiles">
      ${state.categories.map((c) => `
        <a class="tile" href="#/products?category=${c.name}">
          <span class="emoji">${catEmoji(c.name)}</span><b>${esc(catLabel(c.name))}</b><br><small>${c.products} products</small>
        </a>`).join("")}
    </div>
    <h2>Top rated</h2>
    <div class="grid">${res.ok ? res.data.slice(0, 8).map(productCard).join("") : `<div class="alert bad">${esc(res.message)}</div>`}</div>`;
}

async function viewProducts({ params }) {
  const category = params.get("category") || "";
  const q = params.get("q") || "";
  const sort = params.get("sort") || "featured";
  renderCategoryNav(category || (q ? "" : "all"));
  $("#search-q").value = q;

  const query = new URLSearchParams();
  if (category) query.set("category", category);
  if (q) query.set("q", q);
  query.set("sort", sort);
  const res = await api("GET", `/api/products?${query}`);

  const title = q ? `Results for “${esc(q)}”` : category ? esc(catLabel(category)) : "All products";
  const link = (extra) => {
    const p = new URLSearchParams({ ...(category && { category }), ...(q && { q }), sort, ...extra });
    for (const [k, v] of [...p]) if (!v) p.delete(k);
    return `#/products?${p}`;
  };

  view.innerHTML = `
    <div class="listing">
      <aside class="filters card">
        <h3>Category</h3>
        <ul>
          <li><a href="${link({ category: "" })}" class="${!category ? "active" : ""}">All</a></li>
          ${state.categories.map((c) => `<li><a href="${link({ category: c.name })}" class="${category === c.name ? "active" : ""}">${esc(catLabel(c.name))}<span class="muted">${c.products}</span></a></li>`).join("")}
        </ul>
        <h3>Sort by</h3>
        <select id="sort">
          ${[["featured", "Featured"], ["price_asc", "Price: low to high"], ["price_desc", "Price: high to low"], ["rating", "Top rated"], ["name", "Name"]]
            .map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}
        </select>
      </aside>
      <section>
        <div class="listing-head">
          <div><h1>${title}</h1><span class="muted">${res.ok ? `${res.data.length} products` : ""}</span></div>
        </div>
        ${!res.ok ? `<div class="alert bad">${esc(res.message)}</div>`
          : res.data.length ? `<div class="grid">${res.data.map(productCard).join("")}</div>`
          : `<div class="card empty"><div class="icon">🔍</div><h2>No products found</h2><p class="muted">Try a different search or browse a category.</p></div>`}
      </section>
    </div>`;
  $("#sort").addEventListener("change", (e) => { location.hash = link({ sort: e.target.value }); });
}

async function viewProduct({ match }) {
  const res = await api("GET", `/api/products/${match[1]}`);
  if (!res.ok) { view.innerHTML = `<div class="card empty"><div class="icon">📦</div><h2>${esc(res.message)}</h2><a href="#/products">Back to products</a></div>`; return; }
  const p = res.data;
  renderCategoryNav(p.category);
  view.innerHTML = `
    <div class="crumbs"><a href="#/">Home</a> › <a href="#/products?category=${p.category}">${esc(catLabel(p.category))}</a> › ${esc(p.name)}</div>
    <div class="detail">
      <div class="thumb large cat-${esc(p.category)}">${catEmoji(p.category)}</div>
      <div>
        <span class="muted">${esc(catLabel(p.category))} · SKU ${esc(p.sku)}</span>
        <h1>${esc(p.name)}</h1>
        ${stars(p.rating)}
        <div class="price">${money(p.price_cents)}</div>
        <p class="desc">${esc(p.description)}</p>
        ${stockText(p.stock)}
        <div class="buy-row">
          <label>Quantity <input id="qty" type="number" min="1" max="${Math.min(50, p.stock)}" value="1" ${p.stock === 0 ? "disabled" : ""}></label>
          <button id="add" ${p.stock === 0 ? "disabled" : ""}>Add to cart</button>
          <button id="buy" class="secondary" ${p.stock === 0 ? "disabled" : ""}>Buy now</button>
        </div>
        <div class="perks">🚚 Free shipping over $50 &nbsp;·&nbsp; ↩️ 30-day returns &nbsp;·&nbsp; 🛡️ 2-year warranty</div>
      </div>
    </div>
    ${p.related.length ? `<h2>You may also like</h2><div class="grid">${p.related.map(productCard).join("")}</div>` : ""}`;
  const qty = () => Math.max(1, Number($("#qty").value) || 1);
  $("#add").addEventListener("click", () => addToCart(p.id, qty()));
  $("#buy").addEventListener("click", () => addToCart(p.id, qty(), true));
}

function summaryHtml(cart, { showCoupon }) {
  const t = cart.totals;
  return `
    <h2>Order summary</h2>
    <div class="row"><span>Subtotal (${t.units} items)</span><span>${money(t.subtotal_cents)}</span></div>
    ${t.discount_cents ? `<div class="row discount"><span>Discount (${esc(cart.coupon.code)})</span><span>−${money(t.discount_cents)}</span></div>` : ""}
    <div class="row"><span>Shipping</span><span>${t.shipping_cents ? money(t.shipping_cents) : "Free"}</span></div>
    <div class="row total"><span>Total</span><span>${money(t.total_cents)}</span></div>
    ${showCoupon ? (cart.coupon
      ? `<div class="applied"><span>✓ ${esc(cart.coupon.code)}: ${esc(cart.coupon.description)}</span><button class="link" id="remove-coupon">Remove</button></div>`
      : `<form class="coupon" id="coupon-form"><input id="coupon-code" placeholder="Coupon code" maxlength="40"><button class="secondary">Apply</button></form>
         ${cart.coupon_error ? `<div class="alert bad">${esc(cart.coupon_error)}</div>` : ""}`) : ""}`;
}

async function loadCart() {
  const path = state.coupon ? `/api/cart?coupon=${encodeURIComponent(state.coupon)}` : "/api/cart";
  const res = await api("GET", path);
  if (!res.ok && state.coupon) {
    // Applying the coupon broke the request (e.g. a server error). Drop it and show the cart without it.
    toast(res.message, "bad");
    state.coupon = null;
    return loadCart();
  }
  if (res.ok && res.data.coupon_error) state.coupon = null;
  return res;
}

async function viewCart() {
  renderCategoryNav("");
  const res = await loadCart();
  if (!res.ok) { view.innerHTML = `<div class="alert bad">${esc(res.message)}</div>`; return; }
  const cart = res.data;
  $("#cart-count").textContent = cart.totals.units;
  if (!cart.items.length) {
    view.innerHTML = `<div class="card empty"><div class="icon">🛒</div><h2>Your cart is empty</h2><p class="muted">Find something you love.</p><button onclick="location.hash='#/products'">Start shopping</button></div>`;
    return;
  }
  view.innerHTML = `
    <h1>Your cart</h1>
    <div class="two-col">
      <section class="card">
        ${cart.items.map((i) => `
          <div class="line">
            <a href="#/product/${i.id}" class="thumb small cat-${esc(i.category)}">${catEmoji(i.category)}</a>
            <div class="info">
              <a href="#/product/${i.id}">${esc(i.name)}</a><br>
              <span class="muted">${money(i.price_cents)} each</span> · ${stockText(i.stock)}<br>
              <button class="link" data-remove="${i.id}">Remove</button>
            </div>
            <div class="qty">
              <button data-qty="${i.id}" data-to="${i.quantity - 1}" aria-label="Decrease">−</button>
              <span>${i.quantity}</span>
              <button data-qty="${i.id}" data-to="${i.quantity + 1}" aria-label="Increase" ${i.quantity >= Math.min(50, i.stock) ? "disabled" : ""}>+</button>
            </div>
            <div class="line-total">${money(i.price_cents * i.quantity)}</div>
          </div>`).join("")}
      </section>
      <aside class="card summary">
        ${summaryHtml(cart, { showCoupon: true })}
        <button class="big" id="to-checkout">Proceed to checkout</button>
        <p class="muted" style="font-size:13px;text-align:center">Free shipping on orders over $50</p>
      </aside>
    </div>`;

  $$("[data-qty]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    const res2 = await api("PATCH", `/api/cart/items/${b.dataset.qty}`, { quantity: Number(b.dataset.to) });
    if (!res2.ok) toast(res2.message, "bad");
    viewCart();
  }));
  $$("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    const res2 = await api("DELETE", `/api/cart/items/${b.dataset.remove}`);
    if (!res2.ok) toast(res2.message, "bad");
    viewCart();
  }));
  const form = $("#coupon-form");
  if (form) form.addEventListener("submit", (e) => {
    e.preventDefault();
    const code = $("#coupon-code").value.trim();
    if (!code) return;
    state.coupon = code;
    viewCart();
  });
  const rm = $("#remove-coupon");
  if (rm) rm.addEventListener("click", () => { state.coupon = null; viewCart(); });
  $("#to-checkout").addEventListener("click", () => { location.hash = "#/checkout"; });
}

async function viewCheckout() {
  renderCategoryNav("");
  const res = await loadCart();
  if (!res.ok) { view.innerHTML = `<div class="alert bad">${esc(res.message)}</div>`; return; }
  const cart = res.data;
  if (!cart.items.length) { location.hash = "#/cart"; return; }
  view.innerHTML = `
    <h1>Checkout</h1>
    <div class="two-col">
      <form class="card form-grid" id="checkout-form">
        <div id="checkout-error"></div>
        <h2>Shipping address</h2>
        <label>Full name <input id="ship-name" required maxlength="80" value="${esc(state.user.name)}"></label>
        <label>Street address <input id="ship-address" required minlength="3" maxlength="200" placeholder="House 12, Road 5, Dhanmondi"></label>
        <div class="pair">
          <label>City <input id="ship-city" required minlength="2" maxlength="60" placeholder="Dhaka"></label>
          <label>Phone (optional) <input type="tel" maxlength="20" placeholder="01XXXXXXXXX"></label>
        </div>
        <h2>Payment</h2>
        <div class="payment-options">
          <label><input type="radio" name="pay" value="card" checked> 💳 Credit / debit card <span class="muted">(demo, nothing is charged)</span></label>
          <label><input type="radio" name="pay" value="wallet"> 📲 Mobile wallet</label>
          <label><input type="radio" name="pay" value="cash"> 💵 Cash on delivery</label>
        </div>
        <button class="big" id="place">Place order · ${money(cart.totals.total_cents)}</button>
      </form>
      <aside class="card summary">
        ${summaryHtml(cart, { showCoupon: false })}
        <div style="margin-top:12px">
          ${cart.items.map((i) => `<div class="row muted" style="font-size:14px"><span>${i.quantity} × ${esc(i.name)}</span><span>${money(i.price_cents * i.quantity)}</span></div>`).join("")}
        </div>
        <p style="font-size:13px"><a href="#/cart">← Edit cart</a></p>
      </aside>
    </div>`;

  $("#checkout-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#place");
    btn.disabled = true;
    btn.textContent = "Placing your order…";
    const res2 = await api("POST", "/api/orders", {
      payment_method: $("input[name=pay]:checked").value,
      shipping_name: $("#ship-name").value.trim(),
      shipping_address: $("#ship-address").value.trim(),
      shipping_city: $("#ship-city").value.trim(),
      coupon_code: state.coupon || null,
    });
    if (res2.ok) {
      state.coupon = null;
      $("#cart-count").textContent = "0";
      location.hash = `#/orders/${res2.data.id}?placed=1`;
      return;
    }
    $("#checkout-error").innerHTML = `<div class="alert bad">${esc(res2.message)}</div>`;
    btn.disabled = false;
    btn.textContent = `Place order · ${money(cart.totals.total_cents)}`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

async function viewOrders() {
  renderCategoryNav("");
  view.innerHTML = `<h1>My orders</h1>${loading("Loading your orders…")}`;
  const res = await api("GET", "/api/orders");
  if (!res.ok) { view.innerHTML = `<h1>My orders</h1><div class="alert bad">${esc(res.message)}</div>`; return; }
  if (!res.data.length) {
    view.innerHTML = `<h1>My orders</h1><div class="card empty"><div class="icon">📦</div><h2>No orders yet</h2><button onclick="location.hash='#/products'">Start shopping</button></div>`;
    return;
  }
  view.innerHTML = `<h1>My orders</h1>` + res.data.map((o) => {
    const names = o.items.map((i) => `${i.quantity} × ${i.name}`);
    return `
      <div class="card order-card">
        <div>
          <b>Order #${o.id}</b> <span class="badge">${esc(o.status)}</span><br>
          <span class="muted">${when(o.created_at)}</span><br>
          <span>${esc(names.slice(0, 3).join(", "))}${names.length > 3 ? ` and ${names.length - 3} more` : ""}</span>
        </div>
        <div style="text-align:right"><div class="price">${money(o.total_cents)}</div><a href="#/orders/${o.id}">View details →</a></div>
      </div>`;
  }).join("");
}

async function viewOrder({ match, params }) {
  renderCategoryNav("");
  const res = await api("GET", `/api/orders/${match[1]}`);
  if (!res.ok) { view.innerHTML = `<div class="card empty"><div class="icon">📦</div><h2>${esc(res.message)}</h2><a href="#/orders">Back to my orders</a></div>`; return; }
  const o = res.data;
  view.innerHTML = `
    ${params.get("placed") ? `<div class="alert good"><b>Thank you! Your order is confirmed.</b> We'll email you when it ships.</div>` : ""}
    <div class="crumbs"><a href="#/orders">My orders</a> › Order #${o.id}</div>
    <h1>Order #${o.id} <span class="badge">${esc(o.status)}</span></h1>
    <p class="muted">Placed ${when(o.created_at)}</p>
    <div class="two-col">
      <section class="card">
        <table>
          <thead><tr><th>Product</th><th class="num">Price</th><th class="num">Qty</th><th class="num">Total</th></tr></thead>
          <tbody>${o.items.map((i) => `
            <tr><td><a href="#/product/${i.product_id}">${esc(i.name)}</a></td><td class="num">${money(i.unit_price_cents)}</td>
            <td class="num">${i.quantity}</td><td class="num">${money(i.unit_price_cents * i.quantity)}</td></tr>`).join("")}
          </tbody>
        </table>
      </section>
      <aside class="card summary">
        <h2>Summary</h2>
        <div class="row"><span>Subtotal</span><span>${money(o.subtotal_cents)}</span></div>
        ${o.discount_cents ? `<div class="row discount"><span>Discount (${esc(o.coupon_code)})</span><span>−${money(o.discount_cents)}</span></div>` : ""}
        <div class="row"><span>Shipping</span><span>${o.shipping_cents ? money(o.shipping_cents) : "Free"}</span></div>
        <div class="row total"><span>Total</span><span>${money(o.total_cents)}</span></div>
        <h2 style="margin-top:18px">Delivery</h2>
        <p>${esc(o.shipping_name)}<br>${esc(o.shipping_address)}<br>${esc(o.shipping_city)}</p>
        <p class="muted">Paid by ${esc(o.payment_method === "cash" ? "cash on delivery" : o.payment_method)}</p>
      </aside>
    </div>`;
}

function authForm({ title, fields, submitText, footer, onSubmit }) {
  view.innerHTML = `
    <div class="auth card">
      <h1>${title}</h1>
      <form class="form-grid" id="auth-form">
        <div id="auth-error"></div>
        ${fields}
        <button class="big" id="auth-submit">${submitText}</button>
      </form>
      <p class="switch">${footer}</p>
    </div>`;
  $("#auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#auth-submit");
    btn.disabled = true;
    btn.textContent = "Please wait…";
    const error = await onSubmit();
    if (error) {
      $("#auth-error").innerHTML = `<div class="alert bad">${esc(error)}</div>`;
      btn.disabled = false;
      btn.textContent = submitText;
    }
  });
}

function afterLogin(res, params) {
  setSession(res.data.token, res.data.user);
  toast(`Welcome, ${res.data.user.name.split(" ")[0]}!`);
  location.hash = `#${params.get("next") || "/"}`;
}

function viewLogin({ params }) {
  renderCategoryNav("");
  if (state.user) { location.hash = "#/"; return; }
  authForm({
    title: "Log in",
    submitText: "Log in",
    fields: `
      <label>Email <input id="email" type="email" required autocomplete="email"></label>
      <label>Password <input id="password" type="password" required autocomplete="current-password"></label>`,
    footer: `New to ShopLite? <a href="#/register${params.get("next") ? `?next=${encodeURIComponent(params.get("next"))}` : ""}">Create an account</a>`,
    onSubmit: async () => {
      const res = await api("POST", "/api/auth/login", { email: $("#email").value, password: $("#password").value });
      if (!res.ok) return res.message;
      afterLogin(res, params);
    },
  });
}

function viewRegister({ params }) {
  renderCategoryNav("");
  if (state.user) { location.hash = "#/"; return; }
  authForm({
    title: "Create your account",
    submitText: "Create account",
    fields: `
      <label>Full name <input id="name" required maxlength="80" autocomplete="name"></label>
      <label>Email <input id="email" type="email" required maxlength="120" autocomplete="email"></label>
      <label>Password <input id="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password" placeholder="At least 8 characters"></label>
      <label>Confirm password <input id="password2" type="password" required minlength="8" autocomplete="new-password"></label>`,
    footer: `Already have an account? <a href="#/login">Log in</a>`,
    onSubmit: async () => {
      if ($("#password").value !== $("#password2").value) return "The passwords don't match.";
      const res = await api("POST", "/api/auth/register", {
        name: $("#name").value.trim(), email: $("#email").value.trim(), password: $("#password").value,
      });
      if (!res.ok) return res.message;
      afterLogin(res, params);
    },
  });
}

function viewNotFound() {
  view.innerHTML = `<div class="card empty"><div class="icon">🧭</div><h2>Page not found</h2><a href="#/">Go to the home page</a></div>`;
}

// ============================================================================
// Router
// ============================================================================
const routes = [
  [/^\/$/, viewHome],
  [/^\/products$/, viewProducts],
  [/^\/product\/(\d+)$/, viewProduct],
  [/^\/cart$/, viewCart, true],
  [/^\/checkout$/, viewCheckout, true],
  [/^\/orders$/, viewOrders, true],
  [/^\/orders\/(\d+)$/, viewOrder, true],
  [/^\/login$/, viewLogin],
  [/^\/register$/, viewRegister],
];

async function render() {
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(qs || "");
  for (const [pattern, fn, needsAuth] of routes) {
    const match = path.match(pattern);
    if (!match) continue;
    if (needsAuth && !state.token) {
      location.hash = `#/login?next=${encodeURIComponent(path)}`;
      return;
    }
    view.innerHTML = loading();
    window.scrollTo(0, 0);
    await fn({ match, params });
    return;
  }
  viewNotFound();
}

$("#search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#search-q").value.trim();
  location.hash = q ? `#/products?q=${encodeURIComponent(q)}` : "#/products";
});

window.addEventListener("hashchange", render);

(async () => {
  renderAccount();
  const cats = await api("GET", "/api/categories");
  if (cats.ok) state.categories = cats.data;
  refreshCartCount();
  render();
})();
