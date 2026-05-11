const statusDotEl = document.querySelector('#status-dot');
const serverStatusEl = document.querySelector('#server-status');
const terminalWrapEl = document.querySelector('#terminal-wrap');
const connectionToggleBtn = document.querySelector('#connection-toggle-btn');
const tokenManagementPanelEl = document.querySelector('#token-management-panel');
const tokenStatusEl = document.querySelector('#token-status');
const tokenListEl = document.querySelector('#token-list');
const tokenResultEl = document.querySelector('#token-result');
const createTokenFormEl = document.querySelector('#create-token-form');
const refreshTokensBtnEl = document.querySelector('#refresh-tokens-btn');
const createTokenBtnEl = document.querySelector('#create-token-btn');
const tokenTtlValueEl = document.querySelector('#token-ttl-value');
const tokenTtlUnitEl = document.querySelector('#token-ttl-unit');
const tokenAccessTypeEl = document.querySelector('#token-access-type');

let term = null;
let fitAddon = null;
let fitFrame = 0;
let observedTerminalSize = '';
/** @type {WebSocket | null} */
let socket = null;

const session = window.__CLAUDE_CODE_SESSION__ || {};
const sessionToken = getCurrentToken();

function isEmbedMode() {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.has('embed')) return true;
  } catch {
    /* ignore */
  }
  try {
    return window.self !== window.top;
  } catch {
    return false;
  }
}

function applyEmbedClass() {
  const embed = isEmbedMode();
  document.documentElement.classList.toggle('embed', embed);
  document.body.classList.toggle('embed', embed);
  return embed;
}

const embedded = applyEmbedClass();

function getCurrentToken() {
  if (session.token) return String(session.token);
  try {
    const params = new URLSearchParams(window.location.search);
    return params.get('claudecodeToken') || params.get('token') || '';
  } catch {
    return '';
  }
}

function isPrivilegedRole(role) {
  return ['owner', 'administrator', 'admin'].includes(String(role || '').toLowerCase());
}

function setConnectionStatus(kind, label) {
  statusDotEl.classList.remove('online', 'offline');
  if (kind === 'online') statusDotEl.classList.add('online');
  if (kind === 'offline') statusDotEl.classList.add('offline');
  serverStatusEl.textContent = label;
}

function setConnectionButton(state) {
  const isDisconnect = state === 'disconnect';
  connectionToggleBtn.textContent = isDisconnect ? 'Disconnect' : 'Connect';
  connectionToggleBtn.dataset.state = isDisconnect ? 'disconnect' : 'connect';
  connectionToggleBtn.classList.toggle('ghost-button', isDisconnect);
  connectionToggleBtn.classList.toggle('primary-button', !isDisconnect);
  connectionToggleBtn.disabled = false;
}

function wsUrl() {
  const loc = window.location;
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws';
  const basePath = loc.pathname.startsWith('/claudecode') ? '/claudecode' : '';
  return `${scheme}://${loc.host}${basePath}/ws/terminal${loc.search || ''}`;
}

function apiPath(path) {
  if (/^https?:\/\//i.test(path) || path.startsWith('//')) {
    return path;
  }

  const basePath = window.location.pathname.startsWith('/claudecode') ? '/claudecode' : '';
  if (!basePath) return path;
  if (path.startsWith(basePath + '/')) return path;
  if (path.startsWith('/')) return `${basePath}${path}`;
  return `${basePath}/${path}`;
}

function ensureTerm() {
  if (term) return;
  term = new Terminal({
    cursorBlink: true,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    fontSize: 14,
    theme: {
      background: '#fffaf2',
      foreground: '#1f1a14',
      cursor: '#ff7a1a',
      selectionBackground: '#ffd7ad',
      black: '#1f1a14',
      blue: '#e85d04',
      brightBlue: '#ff7a1a',
    },
  });
  const exp = globalThis.FitAddon;
  const FitCtor = exp?.FitAddon ?? exp;
  fitAddon = new FitCtor();
  term.loadAddon(fitAddon);
  term.open(terminalWrapEl);
  term.onData((data) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(new TextEncoder().encode(data));
    }
  });
  scheduleFit();
}

function scheduleFit() {
  if (!term || fitFrame) return;
  fitFrame = requestAnimationFrame(() => {
    fitFrame = 0;
    try {
      fitAddon?.fit();
    } catch {
      // ignore
    }
    sendResize();
  });
}

function sendResize() {
  if (!socket || socket.readyState !== WebSocket.OPEN || !term) return;
  socket.send(
    JSON.stringify({
      type: 'resize',
      cols: term.cols,
      rows: term.rows,
    })
  );
}

function disconnect() {
  if (socket) {
    socket.close();
    socket = null;
  }
  setConnectionButton('connect');
  setConnectionStatus('offline', 'Disconnected');
}

function connect() {
  disconnect();
  ensureTerm();
  term.reset();

  setConnectionStatus(null, 'Connecting…');
  setConnectionButton('disconnect');

  const ws = new WebSocket(wsUrl());
  socket = ws;
  ws.binaryType = 'arraybuffer';
  let wsOpened = false;

  ws.onopen = () => {
    wsOpened = true;
    ws.send(JSON.stringify({ type: 'start' }));
    setConnectionStatus('online', 'Starting Claude Code');
    scheduleFit();
  };

  ws.onmessage = (event) => {
    if (typeof event.data === 'string') {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'error' && msg.message) {
          term.writeln(`\r\n\x1b[31m${msg.message}\x1b[0m\r\n`);
          setConnectionStatus('offline', msg.message);
        }
      } catch {
        // ignore non-JSON text
      }
      return;
    }
    const view = new Uint8Array(event.data);
    term.write(view);
  };

  ws.onerror = () => {
    console.error(
      'WebSocket error (browsers hide details). Check DevTools → Network → WS for /ws/terminal, or Console for mixed-content / CSP.'
    );
    setConnectionStatus('offline', 'WebSocket error — see browser console');
  };

  ws.onclose = (ev) => {
    if (socket !== ws) return;
    if (socket === ws) socket = null;
    setConnectionButton('connect');
    const reason = ev.reason ? `: ${ev.reason}` : '';
    const detail = `code ${ev.code}${reason}`;
    if (!wsOpened) {
      setConnectionStatus('offline', `WebSocket failed (${detail})`);
    } else if (ev.code === 1000) {
      setConnectionStatus('offline', 'Disconnected');
    } else {
      setConnectionStatus('offline', `Disconnected (${detail})`);
    }
  };
}

function apiHeaders(extraHeaders = {}) {
  const headers = new Headers(extraHeaders);
  if (sessionToken) {
    headers.set('X-Claude-Code-Token', sessionToken);
  }
  return headers;
}

async function apiFetch(path, options = {}) {
  const headers = apiHeaders(options.headers || {});
  return fetch(apiPath(path), {
    ...options,
    headers,
  });
}

function setTokenStatus(message, kind = '') {
  if (!tokenStatusEl) return;
  tokenStatusEl.textContent = message;
  tokenStatusEl.className = `token-status ${kind}`.trim();
}

function formatTokenDate(value) {
  if (!value) return 'unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function maskToken(token) {
  if (!token) return 'n/a';
  if (token.length <= 10) return token;
  return `${token.slice(0, 6)}…${token.slice(-4)}`;
}

async function copyToken(token) {
  try {
    await navigator.clipboard.writeText(token);
    setTokenStatus('Token copied to clipboard.', 'is-success');
  } catch {
    setTokenStatus('Could not copy token. Please copy it manually.', 'is-error');
  }
}

function renderTokenResult(tokenInfo) {
  if (!tokenResultEl) return;
  if (!tokenInfo) {
    tokenResultEl.innerHTML = '';
    tokenResultEl.classList.add('hidden');
    return;
  }

  const ttlText = tokenInfo.ttlSeconds ? `${tokenInfo.ttlSeconds} seconds` : 'never expires';
  tokenResultEl.classList.remove('hidden');
  tokenResultEl.innerHTML = `
    <p class="token-result__title">New guest token created</p>
    <p class="token-result__meta">Access: <strong>${escapeHtml(tokenInfo.accessType || 'viewer')}</strong> · TTL: <strong>${escapeHtml(ttlText)}</strong></p>
    <div class="token-result__token">
      <span>${escapeHtml(tokenInfo.token || '')}</span>
      <button class="ghost-button" type="button" data-copy-token="${escapeHtml(tokenInfo.token || '')}">Copy</button>
    </div>
    <p class="token-result__meta">This token is shown once. Store it now if you need to share it later.</p>
  `;

  const copyButton = tokenResultEl.querySelector('[data-copy-token]');
  if (copyButton) {
    copyButton.addEventListener('click', () => {
      void copyToken(copyButton.getAttribute('data-copy-token') || '');
    });
  }
}

function renderTokens(tokens) {
  if (!tokenListEl) return;
  if (!tokens || tokens.length === 0) {
    tokenListEl.innerHTML = '<div class="empty-state"><p>No tokens have been created yet.</p></div>';
    return;
  }

  tokenListEl.innerHTML = tokens
    .map((tokenInfo) => {
      const isRevoked = String(tokenInfo.status || '').toLowerCase() !== 'active';
      const ttlText = tokenInfo.ttlSeconds ? `${tokenInfo.ttlSeconds}s` : 'no expiry';
      const badge = isRevoked ? 'Revoked' : tokenInfo.accessType || 'viewer';
      return `
        <article class="token-card">
          <div class="token-card__header">
            <div>
              <h3 class="token-card__title">${escapeHtml(maskToken(tokenInfo.token))}</h3>
              <div class="token-pill">${escapeHtml(tokenInfo.role || 'guest')}</div>
            </div>
            <span class="token-card__badge">${escapeHtml(badge)}</span>
          </div>
          <div class="token-card__meta">
            <span>Status: <strong>${escapeHtml(tokenInfo.status || 'active')}</strong></span>
            <span>Access: <strong>${escapeHtml(tokenInfo.accessType || 'viewer')}</strong></span>
            <span>Created: <strong>${escapeHtml(formatTokenDate(tokenInfo.createdAt))}</strong></span>
            <span>TTL: <strong>${escapeHtml(ttlText)}</strong></span>
            ${tokenInfo.expiresAt ? `<span>Expires: <strong>${escapeHtml(formatTokenDate(tokenInfo.expiresAt))}</strong></span>` : ''}
          </div>
          <div class="token-card__actions">
            <button class="ghost-button" type="button" data-copy-token="${escapeHtml(tokenInfo.token || '')}">Copy</button>
            <button class="ghost-button" type="button" data-revoke-token="${escapeHtml(tokenInfo.token || '')}" ${isRevoked ? 'disabled' : ''}>Revoke</button>
          </div>
        </article>
      `;
    })
    .join('');

  tokenListEl.querySelectorAll('[data-copy-token]').forEach((button) => {
    button.addEventListener('click', () => {
      void copyToken(button.getAttribute('data-copy-token') || '');
    });
  });

  tokenListEl.querySelectorAll('[data-revoke-token]').forEach((button) => {
    button.addEventListener('click', () => {
      const token = button.getAttribute('data-revoke-token') || '';
      void revokeToken(token);
    });
  });
}

async function loadTokens() {
  if (!tokenListEl) return;
  if (!isPrivilegedRole(session.role)) {
    tokenListEl.innerHTML = '';
    return;
  }

  setTokenStatus('Loading tokens…', '');
  const response = await apiFetch('/api/tokens');
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setTokenStatus(payload.detail || 'Failed to load tokens.', 'is-error');
    return;
  }

  renderTokens(payload.tokens || []);
  setTokenStatus(`Loaded ${String((payload.tokens || []).length)} token(s).`, 'is-success');
}

function ttlSecondsFromForm() {
  const rawValue = Number(tokenTtlValueEl?.value || 0);
  if (!rawValue || rawValue <= 0) return null;
  const unit = tokenTtlUnitEl?.value || 'minutes';
  if (unit === 'hours') return Math.round(rawValue * 3600);
  if (unit === 'days') return Math.round(rawValue * 86400);
  return Math.round(rawValue * 60);
}

async function createGuestToken(event) {
  event.preventDefault();
  if (!isPrivilegedRole(session.role)) return;

  const accessType = tokenAccessTypeEl?.value || 'viewer';
  const ttlSeconds = ttlSecondsFromForm();

  if (ttlSeconds === null) {
    setTokenStatus('Enter a TTL greater than zero to prevent token never expiring.', 'is-error');
    return;
  }

  if (createTokenBtnEl) {
    createTokenBtnEl.disabled = true;
    createTokenBtnEl.textContent = 'Creating…';
  }

  try {
    setTokenStatus('Creating token…', '');
    const response = await apiFetch('/api/tokens', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        accessType,
        ttlSeconds,
      }),
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      setTokenStatus(payload.detail || 'Token creation failed.', 'is-error');
      return;
    }

    renderTokenResult(payload);
    await loadTokens();
    setTokenStatus('Token created successfully.', 'is-success');
    if (createTokenFormEl) createTokenFormEl.reset();
    if (tokenTtlUnitEl) tokenTtlUnitEl.value = 'minutes';
    if (tokenAccessTypeEl) tokenAccessTypeEl.value = 'viewer';
  } finally {
    if (createTokenBtnEl) {
      createTokenBtnEl.disabled = false;
      createTokenBtnEl.textContent = 'Create guest token';
    }
  }
}

async function revokeToken(token) {
  if (!token) return;
  if (!confirm('Revoke this token? It will stop working immediately.')) return;

  setTokenStatus('Revoking token…', '');
  const response = await apiFetch(`/api/tokens/${encodeURIComponent(token)}`, {
    method: 'DELETE',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setTokenStatus(payload.detail || 'Failed to revoke token.', 'is-error');
    return;
  }
  setTokenStatus('Token revoked.', 'is-success');
  await loadTokens();
}

function initTokenManagement() {
  if (!tokenManagementPanelEl) return;
  if (!isPrivilegedRole(session.role)) {
    // Remove the panel entirely from the DOM (not just hiding)
    // This prevents dev-tool manipulation and unauthorized form access
    tokenManagementPanelEl.remove();
    return;
  }

  // Panel is visible; ensure it's not hidden
  tokenManagementPanelEl.classList.remove('hidden');
  setTokenStatus(`Signed in as ${session.role || 'owner'}.`, 'is-success');
  void loadTokens();

  if (createTokenFormEl) {
    createTokenFormEl.addEventListener('submit', (event) => {
      void createGuestToken(event);
    });
  }

  if (refreshTokensBtnEl) {
    refreshTokensBtnEl.addEventListener('click', () => {
      void loadTokens();
    });
  }
}

connectionToggleBtn.addEventListener('click', () => {
  if (connectionToggleBtn.dataset.state === 'disconnect') {
    disconnect();
    return;
  }
  connect();
});

setConnectionButton('connect');
initTokenManagement();

window.addEventListener('resize', scheduleFit);
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', scheduleFit);
}

if (terminalWrapEl && typeof ResizeObserver !== 'undefined') {
  const ro = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect;
    if (!rect) return;
    const nextSize = `${Math.round(rect.width)}x${Math.round(rect.height)}`;
    if (nextSize === observedTerminalSize) return;
    observedTerminalSize = nextSize;
    scheduleFit();
  });
  ro.observe(terminalWrapEl);
}

if (embedded) {
  connect();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}
