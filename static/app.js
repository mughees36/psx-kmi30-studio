const STOCKS_API = "/api/stocks";

const state = {
    token: localStorage.getItem("token") || "",
    userEmail: localStorage.getItem("userEmail") || "",
    stocks: [],
    favoriteSymbols: [],
    favoriteStocks: [],
    selectedStock: null,
    selectedSymbol: null,
    currentView: "auth",
    currentHistoryRange: "1M",
    activeTab: "overview",
};

function $(id) { return document.getElementById(id); }

function formatNumber(value) {
    return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function formatPrice(value) {
    return `Rs. ${Number(value || 0).toFixed(2)}`;
}

function formatCompactDate(timestamp, withTime = false) {
    return new Intl.DateTimeFormat("en-US", withTime
        ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
        : { month: "short", day: "numeric", year: "2-digit" }
    ).format(new Date(timestamp * 1000));
}

// ── Toast ──────────────────────────────────────────────
function showToast(message, type = "default", duration = 3500) {
    const stack = $("toast-stack");
    const toast = document.createElement("div");
    toast.className = `toast${type !== "default" ? ` ${type}` : ""}`;
    toast.textContent = message;
    stack.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.3s";
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ── Button loading state ───────────────────────────────
function setButtonLoading(btn, label) {
    btn.disabled = true;
    btn._originalHTML = btn.innerHTML;
    btn.innerHTML = `<span class="spin"></span>${label}`;
}

function resetButton(btn) {
    btn.disabled = false;
    btn.innerHTML = btn._originalHTML || btn.textContent;
}

// ── Error message normalizer ───────────────────────────
function normalizeErrorMessage(detail) {
    if (!detail) return "Request failed";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail.map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object" && item.msg) {
                const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "field";
                return `${field}: ${item.msg}`;
            }
            return JSON.stringify(item);
        }).join(" | ");
    }
    if (typeof detail === "object") {
        if (detail.detail) return normalizeErrorMessage(detail.detail);
        if (detail.msg) return detail.msg;
        return JSON.stringify(detail);
    }
    return String(detail);
}

// ── Nav / View ─────────────────────────────────────────
function showNav(show) {
    $("main-nav").style.display = show ? "flex" : "none";
}

function showView(viewName) {
    state.currentView = viewName;
    ["auth", "home", "favorites", "detail"].forEach((view) => {
        $(`${view}-view`).classList.toggle("active", view === viewName);
    });
    $("nav-home").classList.toggle("active", viewName === "home");
    $("nav-favorites").classList.toggle("active", viewName === "favorites");
    $("nav-detail").classList.toggle("active", viewName === "detail");
    $("nav-detail").style.display = state.selectedStock ? "inline-flex" : "none";
}

// ── Tabs ───────────────────────────────────────────────
function switchTab(tabName) {
    state.activeTab = tabName;
    ["overview", "financials", "dividends"].forEach((t) => {
        $(`tab-${t}`).classList.toggle("active", t === tabName);
        $(`tab-btn-${t}`).classList.toggle("active", t === tabName);
    });
}

// ── Auth modes ─────────────────────────────────────────
function setAuthMessage(message) {
    $("auth-message").textContent = message || "";
}

function showSignupMode() {
    $("auth-title").textContent = "Create your account";
    $("auth-helper").textContent = "Sign up with your email, password, and phone number.";
    $("auth-primary-btn").textContent = "Create Account";
    $("auth-primary-btn").onclick = signup;
    $("auth-secondary-btn").textContent = "I already have an account";
    $("auth-secondary-btn").onclick = showLoginMode;
    $("phone-field").style.display = "flex";
    $("phone").value = "";
    setAuthMessage("");
    showView("auth");
}

function showLoginMode() {
    $("auth-title").textContent = "Welcome back";
    $("auth-helper").textContent = "Log in with your email and password.";
    $("auth-primary-btn").textContent = "Log In";
    $("auth-primary-btn").onclick = login;
    $("auth-secondary-btn").textContent = "Create a new account";
    $("auth-secondary-btn").onclick = showSignupMode;
    $("phone-field").style.display = "none";
    $("phone").value = "";
    setAuthMessage("");
    showView("auth");
}

function saveSession(email, token) {
    state.userEmail = email;
    state.token = token;
    localStorage.setItem("userEmail", email);
    localStorage.setItem("token", token);
}

function clearSession() {
    state.token = "";
    state.userEmail = "";
    state.stocks = [];
    state.favoriteSymbols = [];
    state.favoriteStocks = [];
    state.selectedStock = null;
    state.selectedSymbol = null;
    localStorage.removeItem("userEmail");
    localStorage.removeItem("token");
}

function isFavorite(symbol) {
    const normalized = String(symbol || "").split(" ")[0].trim().toUpperCase();
    return state.favoriteSymbols.includes(normalized);
}

// ── API ────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const response = await fetch(url, { ...options, headers });
    let data = null;
    try { data = await response.json(); } catch { data = null; }

    if (!response.ok) {
        if (response.status === 401) {
            clearSession();
            showNav(false);
            showLoginMode();
        }
        throw new Error(normalizeErrorMessage(data && data.detail ? data.detail : data));
    }
    return data;
}

async function saveTokenFromCredentials(email, password) {
    const data = await apiFetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    saveSession(email, data.access_token);
}

// ── Auth actions ───────────────────────────────────────
async function signup() {
    const email = $("email").value.trim();
    const password = $("password").value;
    const phone = $("phone").value.trim();
    if (!email || !password || !phone) {
        setAuthMessage("Email, password, and phone number are required.");
        return;
    }
    const btn = $("auth-primary-btn");
    setButtonLoading(btn, "Creating…");
    try {
        await apiFetch("/auth/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, phone }),
        });
        await saveTokenFromCredentials(email, password);
        setAuthMessage("Account created! Loading KMI30 data…");
        await loadHome();
    } catch (error) {
        setAuthMessage(error.message);
        resetButton(btn);
    }
}

async function login() {
    const email = $("email").value.trim();
    const password = $("password").value;
    if (!email || !password) {
        setAuthMessage("Email and password are required.");
        return;
    }
    const btn = $("auth-primary-btn");
    setButtonLoading(btn, "Logging in…");
    try {
        await saveTokenFromCredentials(email, password);
        setAuthMessage("Login successful. Loading KMI30 data…");
        await loadHome();
    } catch (error) {
        setAuthMessage(error.message);
        resetButton(btn);
    }
}

function logout() {
    clearSession();
    showNav(false);
    showSignupMode();
}

// ── Home stats ─────────────────────────────────────────
function updateHomeStats() {
    $("hero-copy").textContent = state.userEmail
        ? `Signed in as ${state.userEmail} · Data sourced from the official PSX portal.`
        : "Browse the current KMI30 constituents from the official PSX data portal.";
    const positive = state.stocks.filter((s) => s.change > 0).length;
    const totalVolume = state.stocks.reduce((sum, s) => sum + s.volume, 0);
    const topSymbol = state.stocks.length
        ? [...state.stocks].sort((a, b) => b.change_percent - a.change_percent)[0].symbol
        : "—";
    $("stat-count").textContent = state.stocks.length || "—";
    $("stat-positive").textContent = positive || "—";
    $("stat-top-symbol").textContent = topSymbol;
    $("stat-total-volume").textContent = formatNumber(totalVolume);
}

// ── Filters ────────────────────────────────────────────
function getWeightFilteredStocks(stocks, options) {
    const query = (options.query || "").trim().toLowerCase();
    const minWeight = options.minWeight === "" ? null : Number(options.minWeight);
    const maxWeight = options.maxWeight === "" ? null : Number(options.maxWeight);
    const sort = options.sort || "weight-desc";

    let filtered = stocks.filter((s) => {
        const matchesQuery = !query || s.symbol.toLowerCase().includes(query) || s.name.toLowerCase().includes(query);
        const matchesMin = minWeight === null || isNaN(minWeight) || s.idx_weight_percent >= minWeight;
        const matchesMax = maxWeight === null || isNaN(maxWeight) || s.idx_weight_percent <= maxWeight;
        return matchesQuery && matchesMin && matchesMax;
    });

    return [...filtered].sort((a, b) => {
        if (sort === "weight-asc") return a.idx_weight_percent - b.idx_weight_percent;
        if (sort === "change-desc") return b.change_percent - a.change_percent;
        if (sort === "name-asc") return a.name.localeCompare(b.name);
        return b.idx_weight_percent - a.idx_weight_percent;
    });
}

function resetHomeFilters() {
    $("stock-search").value = "";
    $("stock-weight-min").value = "";
    $("stock-weight-max").value = "";
    $("stock-sort").value = "weight-desc";
    renderStocks();
}

function resetFavoriteFilters() {
    $("favorite-search").value = "";
    $("favorite-weight-min").value = "";
    $("favorite-weight-max").value = "";
    $("favorite-sort").value = "weight-desc";
    renderFavorites();
}

// ── Skeleton cards ─────────────────────────────────────
function renderSkeletonCards(containerId, count = 6) {
    const container = $(containerId);
    container.innerHTML = "";
    for (let i = 0; i < count; i++) {
        container.innerHTML += `
            <div class="skel-card">
                <div style="display:flex;justify-content:space-between;">
                    <div style="flex:1;">
                        <div class="skel skel-line short" style="margin-bottom:8px;"></div>
                        <div class="skel skel-line medium"></div>
                    </div>
                    <div class="skel skel-circle" style="margin-left:12px;"></div>
                </div>
                <div class="skel skel-line tall"></div>
                <div class="skel skel-line short"></div>
                <div style="display:flex;gap:8px;">
                    <div class="skel" style="height:36px;width:100px;border-radius:999px;"></div>
                    <div class="skel" style="height:36px;width:100px;border-radius:999px;"></div>
                </div>
            </div>`;
    }
}

// ── Stock cards ────────────────────────────────────────
function renderStocks() {
    const list = $("stock-list");
    const empty = $("stocks-empty");
    const filtered = getWeightFilteredStocks(state.stocks, {
        query: $("stock-search").value,
        minWeight: $("stock-weight-min").value,
        maxWeight: $("stock-weight-max").value,
        sort: $("stock-sort").value,
    });
    list.innerHTML = "";
    if (!filtered.length) { empty.style.display = "block"; return; }
    empty.style.display = "none";
    renderStockCards(list, filtered);
}

function renderStockCards(container, stocks) {
    container.innerHTML = "";
    stocks.forEach((stock) => {
        const changeClass = stock.change >= 0 ? "positive" : "negative";
        const favorite = isFavorite(stock.symbol);
        const card = document.createElement("article");
        card.className = "stock-card";
        card.innerHTML = `
            <div class="stock-top">
                <div>
                    <div class="stock-symbol">${stock.symbol}</div>
                    <div class="stock-name">${stock.name}</div>
                </div>
                <div class="stock-price">${formatPrice(stock.current)}</div>
            </div>
            <div class="chip-row">
                <span class="chip">LDCP ${stock.ldcp.toFixed(2)}</span>
                <span class="chip">Wt. ${stock.idx_weight_percent.toFixed(2)}%</span>
            </div>
            <div class="${changeClass}" style="font-weight:600;font-size:0.93rem;">
                ${stock.change >= 0 ? "+" : ""}${stock.change.toFixed(2)} (${stock.change_percent.toFixed(2)}%)
            </div>
            <div style="color:var(--muted);font-size:0.82rem;">
                Vol ${formatNumber(stock.volume)} &nbsp;·&nbsp; Mkt Cap ${formatNumber(stock.market_cap_mn)} Mn
            </div>
            <div class="inline-actions">
                <button class="btn" onclick="openStockDetail('${stock.symbol}')">Open Detail</button>
                <button class="${favorite ? "danger-btn" : "ghost-btn"}" onclick="toggleFavorite('${stock.symbol}')">
                    ${favorite ? "Remove" : "Watchlist"}
                </button>
            </div>`;
        container.appendChild(card);
    });
}

// ── Favorites ──────────────────────────────────────────
function updateFavoriteStats() {
    const positive = state.favoriteStocks.filter((s) => s.change > 0).length;
    const totalVolume = state.favoriteStocks.reduce((sum, s) => sum + s.volume, 0);
    const topSymbol = state.favoriteStocks.length
        ? [...state.favoriteStocks].sort((a, b) => b.change_percent - a.change_percent)[0].symbol
        : "—";
    $("favorite-count").textContent = state.favoriteStocks.length || "—";
    $("favorite-positive").textContent = positive || "—";
    $("favorite-top-symbol").textContent = topSymbol;
    $("favorite-total-volume").textContent = formatNumber(totalVolume);
}

function renderFavorites() {
    const list = $("favorite-list");
    const empty = $("favorites-empty");
    const filtered = getWeightFilteredStocks(state.favoriteStocks, {
        query: $("favorite-search").value,
        minWeight: $("favorite-weight-min").value,
        maxWeight: $("favorite-weight-max").value,
        sort: $("favorite-sort").value,
    });
    if (!filtered.length) { list.innerHTML = ""; empty.style.display = "block"; return; }
    empty.style.display = "none";
    renderStockCards(list, filtered);
}

async function refreshStocks() {
    const btn = $("refresh-btn");
    setButtonLoading(btn, "Loading…");
    $("stocks-loading").style.display = "block";
    $("stocks-error").style.display = "none";
    $("stock-list").innerHTML = "";
    $("stocks-empty").style.display = "none";
    renderSkeletonCards("stocks-skeleton", 6);

    try {
        state.stocks = await apiFetch(`${STOCKS_API}/kmi30`);
        updateHomeStats();
        renderStocks();
    } catch (error) {
        $("stocks-error-msg").textContent = error.message;
        $("stocks-error").style.display = "block";
    } finally {
        $("stocks-loading").style.display = "none";
        resetButton(btn);
    }
}

async function refreshFavorites() {
    $("favorites-loading").style.display = "block";
    try {
        const data = await apiFetch(`${STOCKS_API}/favorites`);
        state.favoriteSymbols = (data.symbols || []).map((s) => String(s).toUpperCase());
        state.favoriteStocks = data.stocks || [];
        updateFavoriteStats();
        renderFavorites();
        renderStocks();
    } catch (error) {
        showToast(error.message, "error");
    } finally {
        $("favorites-loading").style.display = "none";
    }
}

async function toggleFavorite(symbol) {
    const normalized = String(symbol || "").split(" ")[0].trim().toUpperCase();
    const method = isFavorite(normalized) ? "DELETE" : "POST";
    const adding = method === "POST";
    try {
        await apiFetch(`${STOCKS_API}/favorites/${normalized}`, { method });
        await refreshFavorites();
        if (state.selectedStock && state.selectedStock.symbol.split(" ")[0].toUpperCase() === normalized) {
            updateDetailFavoriteButton(normalized);
        }
        showToast(adding ? `${normalized} added to watchlist` : `${normalized} removed from watchlist`, "success");
    } catch (error) {
        showToast(error.message, "error");
    }
}

// ── Charts ─────────────────────────────────────────────
function createBarChartSvg(series) {
    if (!series.values || !series.values.length) {
        return '<div class="empty-state">Chart data is not available.</div>';
    }

    const W = 640, H = 220, PAD = 40;
    const positiveValues = series.values.filter((v) => v > 0);
    const max = positiveValues.length ? Math.max(...positiveValues) : Math.max(...series.values, 1);
    const min = Math.min(...series.values, 0);
    const spread = Math.max(max - min, 1);
    const n = series.values.length;
    const slotW = (W - PAD * 2) / n;
    const barW = Math.min(slotW * 0.55, 60);

    const bars = series.values.map((value, i) => {
        const x = PAD + i * slotW + slotW / 2;
        const barH = Math.max(((H - PAD * 2) * Math.max(value, 0)) / spread, 2);
        const y = H - PAD - barH;
        const isNeg = value < 0;
        const fill = isNeg ? "#d14d4d" : "url(#barGrad)";
        const label = String(series.labels[i] || "");
        const displayLabel = label.length > 6 ? label.slice(0, 6) : label;
        const numDisplay = Math.abs(value) >= 1000000
            ? `${(value / 1000000).toFixed(1)}M`
            : Math.abs(value) >= 1000
            ? `${(value / 1000).toFixed(1)}K`
            : Number(value).toFixed(2);
        return `
            <rect x="${x - barW / 2}" y="${y}" width="${barW}" height="${barH}" rx="6" fill="${fill}"/>
            <text x="${x}" y="${H - PAD + 14}" text-anchor="middle" font-size="11" fill="#607089">${displayLabel}</text>
            <text x="${x}" y="${y - 5}" text-anchor="middle" font-size="10" fill="#11203b">${isNeg ? "-" : ""}${numDisplay}</text>`;
    }).join("");

    return `
        <svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img" aria-label="${series.title}">
            <defs>
                <linearGradient id="barGrad" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stop-color="#0d8a6a"/>
                    <stop offset="100%" stop-color="#0f3d66"/>
                </linearGradient>
            </defs>
            <line x1="${PAD}" y1="${H - PAD}" x2="${W - PAD}" y2="${H - PAD}" stroke="rgba(17,32,59,0.12)"/>
            ${bars}
        </svg>`;
}

function getHistoricalPoints(history, rangeName) {
    const range = (rangeName || "1M").toUpperCase();
    if (range === "1D") {
        return (history.intraday || []).map((p) => ({ ...p, displayLabel: p.label || formatCompactDate(p.timestamp, true) }));
    }
    const eod = history.eod || [];
    if (!eod.length) return [];

    const latestTs = eod[eod.length - 1].timestamp * 1000;
    const endDate = new Date(latestTs);
    let startDate = new Date(latestTs);
    if (range === "YTD") startDate = new Date(endDate.getFullYear(), 0, 1);
    else if (range === "1M") startDate.setMonth(startDate.getMonth() - 1);
    else if (range === "6M") startDate.setMonth(startDate.getMonth() - 6);
    else if (range === "1Y") startDate.setFullYear(startDate.getFullYear() - 1);
    else if (range === "3Y") startDate.setFullYear(startDate.getFullYear() - 3);
    else if (range === "5Y") startDate.setFullYear(startDate.getFullYear() - 5);
    else startDate = new Date(0);

    return eod
        .filter((p) => p.timestamp * 1000 >= startDate.getTime())
        .map((p) => ({ ...p, displayLabel: p.label || formatCompactDate(p.timestamp, false) }));
}

function createLineChartSvg(points, title) {
    if (!points.length) return '<div class="empty-state">Price history is not available for this range.</div>';

    const W = 640, H = 240, PAD = 40;
    const values = points.map((p) => p.close);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const spread = Math.max(max - min, 1);
    const stepX = points.length > 1 ? (W - PAD * 2) / (points.length - 1) : 0;

    const coords = points.map((p, i) => ({
        x: PAD + i * stepX,
        y: H - PAD - ((p.close - min) / spread) * (H - PAD * 2),
        point: p,
    }));

    const path = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
    const areaPath = `${path} L ${coords[coords.length - 1].x} ${H - PAD} L ${coords[0].x} ${H - PAD} Z`;

    const isPositive = values[values.length - 1] >= values[0];
    const lineColor = isPositive ? "#0d8a6a" : "#d14d4d";
    const areaColor = isPositive ? "rgba(13,138,106,0.12)" : "rgba(209,77,77,0.08)";

    const labelStep = Math.max(1, Math.floor(coords.length / 5));
    const markers = coords
        .filter((_, i) => i === 0 || i === coords.length - 1 || i % labelStep === 0)
        .map((c) => `
            <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="3" fill="${lineColor}" opacity="0.6"/>
            <text x="${c.x.toFixed(1)}" y="${H - 10}" text-anchor="middle" font-size="10" fill="#607089">${c.point.displayLabel}</text>`)
        .join("");

    const latest = points[points.length - 1];
    const changeFromFirst = ((latest.close - values[0]) / values[0]) * 100;
    const changeSign = changeFromFirst >= 0 ? "+" : "";

    return `
        <svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img" aria-label="${title}">
            <defs>
                <linearGradient id="lineAreaGrad" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stop-color="${areaColor}"/>
                    <stop offset="100%" stop-color="transparent"/>
                </linearGradient>
            </defs>
            <line x1="${PAD}" y1="${H - PAD}" x2="${W - PAD}" y2="${H - PAD}" stroke="rgba(17,32,59,0.1)"/>
            <path d="${areaPath}" fill="url(#lineAreaGrad)"/>
            <path d="${path}" fill="none" stroke="${lineColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            ${markers}
            <text x="${PAD}" y="${PAD - 8}" font-size="10" fill="#607089">Low ${formatPrice(min)}</text>
            <text x="${W - PAD}" y="${PAD - 8}" text-anchor="end" font-size="10" fill="#607089">High ${formatPrice(max)}</text>
            <text x="${W - PAD}" y="${PAD + 10}" text-anchor="end" font-size="11" fill="${lineColor}" font-weight="600">${changeSign}${changeFromFirst.toFixed(2)}%</text>
        </svg>`;
}

function renderHistoryRangeButtons() {
    const container = $("history-range-buttons");
    const ranges = ["1D", "1M", "6M", "YTD", "1Y", "3Y", "5Y"];
    container.innerHTML = ranges.map((r) =>
        `<button class="range-btn${state.currentHistoryRange === r ? " active" : ""}" onclick="setHistoryRange('${r}')">${r}</button>`
    ).join("");
}

function renderHistoricalChart(detail) {
    const history = detail.historical_prices;
    state.currentHistoryRange = history.default_range || state.currentHistoryRange || "1M";
    const points = getHistoricalPoints(history, state.currentHistoryRange);
    $("history-chart-title").textContent = `Price Trend (${state.currentHistoryRange})`;
    $("history-chart").innerHTML = createLineChartSvg(points, `${detail.symbol} price history`);
    renderHistoryRangeButtons();
}

function setHistoryRange(rangeName) {
    state.currentHistoryRange = rangeName;
    if (!state.selectedStock) return;
    const points = getHistoricalPoints(state.selectedStock.historical_prices, rangeName);
    $("history-chart-title").textContent = `Price Trend (${rangeName})`;
    $("history-chart").innerHTML = createLineChartSvg(points, `${state.selectedStock.symbol} price history`);
    renderHistoryRangeButtons();
}

// ── Metrics & tables ───────────────────────────────────
function renderMetricCards(containerId, metrics) {
    const container = $(containerId);
    container.innerHTML = "";
    (metrics || []).forEach((m) => {
        const card = document.createElement("div");
        card.className = "metric";
        card.innerHTML = `<small>${m.label}</small><strong>${m.value}</strong>`;
        container.appendChild(card);
    });
}

function renderTable(containerId, tableData) {
    const container = $(containerId);
    if (!tableData || !tableData.periods || !tableData.periods.length) {
        container.innerHTML = '<div class="empty-state">No data available.</div>';
        return;
    }
    const head = tableData.periods.map((p) => `<th>${p}</th>`).join("");
    const rows = tableData.rows.map((row) => {
        const cells = row.values.map((v) => `<td>${v}</td>`).join("");
        return `<tr><th style="text-align:left;font-weight:500;color:var(--ink);">${row.label}</th>${cells}</tr>`;
    }).join("");
    container.innerHTML = `<table><thead><tr><th>Metric</th>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

function renderAnnouncements(items) {
    const container = $("announcements-table");
    if (!items.length) { container.innerHTML = '<div class="empty-state">No announcements available.</div>'; return; }
    const rows = items.map((item) => `<tr><td style="white-space:nowrap;">${item.date}</td><td>${item.title}</td></tr>`).join("");
    container.innerHTML = `<table><thead><tr><th>Date</th><th>Title</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderDividendHistory(items) {
    const container = $("dividend-history-table");
    if (!items.length) { container.innerHTML = '<div class="empty-state">No dividend history available.</div>'; return; }
    const rows = items.map((item) => `
        <tr>
            <td style="white-space:nowrap;">${item.date}</td>
            <td>${item.period}</td>
            <td>${item.details}</td>
            <td>${item.dividend_amount || "—"}</td>
            <td style="white-space:nowrap;">${item.book_closure}</td>
        </tr>`).join("");
    container.innerHTML = `<table><thead><tr><th>Date</th><th>Period</th><th>Details</th><th>Amount</th><th>Book Closure</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ── Detail ─────────────────────────────────────────────
function updateDetailFavoriteButton(symbol) {
    const btn = $("detail-favorite-btn");
    const fav = isFavorite(symbol);
    btn.textContent = fav ? "Remove from Watchlist" : "Add to Watchlist";
    btn.className = fav ? "danger-btn" : "btn";
    btn.onclick = () => toggleFavorite(symbol);
}

function renderStockDetail(detail) {
    state.selectedStock = detail;
    state.currentHistoryRange = detail.historical_prices?.default_range || "1M";

    $("nav-detail").style.display = "inline-flex";
    $("detail-loading").style.display = "none";
    $("detail-error").style.display = "none";
    $("detail-content").style.display = "block";

    // Header
    const normalized = detail.symbol.split(" ")[0].toUpperCase();
    $("detail-eyebrow").textContent = `${detail.sector} · ${detail.fiscal_year_end || ""}`;
    $("detail-sector-badge").textContent = detail.sector;
    $("detail-name").textContent = `${normalized} — ${detail.name}`;
    $("detail-current-price").textContent = formatPrice(detail.current_price);
    $("detail-as-of").textContent = `As of ${detail.as_of}`;

    const changeSign = detail.absolute_change >= 0 ? "+" : "";
    const changeBadge = $("detail-change-badge");
    changeBadge.textContent = `${changeSign}${detail.absolute_change.toFixed(2)} (${detail.percent_change.toFixed(2)}%)`;
    changeBadge.className = `detail-change-badge ${detail.absolute_change >= 0 ? "change-positive" : "change-negative"}`;

    updateDetailFavoriteButton(normalized);

    // Valuation band
    const vBand = $("valuation-band");
    if (detail.fair_price !== null && detail.valuation_eps !== null) {
        vBand.style.display = "flex";
        $("val-fair-price").textContent = formatPrice(detail.fair_price);
        $("val-method").textContent = detail.sector_pe_method || "";
        $("val-eps").textContent = detail.valuation_eps !== null ? detail.valuation_eps.toFixed(2) : "—";
        $("val-peers").textContent = `${detail.sector_pe_peer_count} peer${detail.sector_pe_peer_count !== 1 ? "s" : ""} · Sector P/E ${detail.sector_average_pe !== null ? detail.sector_average_pe.toFixed(2) : "—"}`;

        const upsidePct = ((detail.fair_price - detail.current_price) / detail.current_price) * 100;
        const upsideEl = $("val-upside");
        const sign = upsidePct >= 0 ? "+" : "";
        upsideEl.textContent = `${sign}${upsidePct.toFixed(1)}% upside`;
        upsideEl.className = `val-upside-pill ${upsidePct >= 0 ? "pill-up" : "pill-down"}`;
    } else {
        vBand.style.display = "none";
    }

    // Charts
    renderHistoricalChart(detail);
    $("price-chart-title").textContent = "Price Snapshot (Today)";
    $("price-chart").innerHTML = createBarChartSvg(detail.price_chart);
    $("financial-chart-title").textContent = detail.financial_chart.title || "Annual Revenue";
    $("financial-chart").innerHTML = createBarChartSvg(detail.financial_chart);
    $("ratio-chart-title").textContent = detail.ratio_chart.title || "Net Profit Margin";
    $("ratio-chart").innerHTML = createBarChartSvg(detail.ratio_chart);

    // Metrics
    renderMetricCards("quote-metrics", detail.quote_metrics);
    renderMetricCards("fundamentals", detail.fundamentals);
    renderMetricCards("equity-profile", detail.equity_profile);

    $("business-description").textContent = detail.business_description || "";

    const profileFacts = [];
    if (detail.address) profileFacts.push({ label: "Address", value: detail.address });
    if (detail.registrar) profileFacts.push({ label: "Registrar", value: detail.registrar });
    if (detail.auditor) profileFacts.push({ label: "Auditor", value: detail.auditor });
    if (detail.key_people && detail.key_people.length) profileFacts.push({ label: "Key People", value: detail.key_people.join(", ") });
    renderMetricCards("company-facts", profileFacts);
    if (detail.website) {
        const websiteUrl = detail.website.startsWith("http") ? detail.website : `https://${detail.website}`;
        const websiteCard = document.createElement("div");
        websiteCard.className = "metric";
        websiteCard.innerHTML = `<small>Website</small><strong><a href="${websiteUrl}" target="_blank" rel="noopener">${detail.website}</a></strong>`;
        $("company-facts").appendChild(websiteCard);
    }

    // Tables
    renderTable("annual-financials", detail.annual_financials);
    renderTable("quarterly-financials", detail.quarterly_financials);
    renderTable("ratios-table", detail.ratios);
    renderAnnouncements(detail.announcements);
    renderDividendHistory(detail.dividend_history);

    // Reset to overview tab
    switchTab("overview");
}

async function openStockDetail(symbol) {
    state.selectedSymbol = symbol;
    showView("detail");
    $("detail-loading").style.display = "block";
    $("detail-error").style.display = "none";
    $("detail-content").style.display = "none";

    try {
        const detail = await apiFetch(`${STOCKS_API}/${symbol}`);
        renderStockDetail(detail);
    } catch (error) {
        $("detail-loading").style.display = "none";
        $("detail-error-msg").textContent = error.message;
        $("detail-error").style.display = "block";
        $("detail-retry-btn").onclick = () => openStockDetail(symbol);
    }
}

// ── Bootstrap ──────────────────────────────────────────
let _indexRefreshTimer = null;

async function refreshKMI30Index() {
    try {
        const data = await apiFetch(`${STOCKS_API}/kmi30-index`);
        const ticker = document.getElementById("kmi30-ticker");
        const levelEl = document.getElementById("idx-level");
        const changeEl = document.getElementById("idx-change");
        const asOfEl = document.getElementById("idx-as-of");

        levelEl.textContent = data.level.toLocaleString("en-PK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

        const sign = data.change >= 0 ? "+" : "";
        changeEl.textContent = `${sign}${data.change.toLocaleString("en-PK", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${sign}${data.change_percent.toFixed(2)}%)`;
        changeEl.className = "idx-change " + (data.change >= 0 ? "positive" : "negative");

        const now = new Date();
        asOfEl.textContent = `as of ${now.toLocaleTimeString("en-PK", { hour: "2-digit", minute: "2-digit" })}`;
        ticker.style.display = "flex";
    } catch (_) {
        // silently skip if index data unavailable
    }
}

async function loadHome() {
    showNav(true);
    refreshKMI30Index();
    if (_indexRefreshTimer) clearInterval(_indexRefreshTimer);
    _indexRefreshTimer = setInterval(refreshKMI30Index, 60000);
    await refreshStocks();
    await refreshFavorites();
    showView("home");
}

async function bootstrap() {
    if (state.token) {
        showNav(true);
        await loadHome();
        return;
    }
    showNav(false);
    showSignupMode();
}

bootstrap();
