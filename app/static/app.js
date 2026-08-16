const statusDotEl = document.querySelector('#status-dot');
const serverStatusEl = document.querySelector('#server-status');
const terminalWrapEl = document.querySelector('#terminal-wrap');
const terminalPanelEl = document.querySelector('#terminal-panel');
const terminalFullscreenBtnEl = document.querySelector('#terminal-fullscreen-btn');
const agentJobsLinkEl = document.querySelector('#agent-jobs-link');
const terminalAuthLinkEl = document.querySelector('#terminal-auth-link');
const terminalAuthLinkUrlEl = document.querySelector('#terminal-auth-link-url');
const terminalAuthLinkCopyEl = document.querySelector('#terminal-auth-link-copy');
const terminalAuthLinkOpenEl = document.querySelector('#terminal-auth-link-open');
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
const tokenSessionModeEl = document.querySelector('#token-session-mode');
const tokenSessionsModalEl = document.querySelector('#token-sessions-modal');
const tokenSessionsModalFormEl = document.querySelector('#token-sessions-modal-form');
const tokenSessionsModalCloseEl = document.querySelector('#token-sessions-modal-close');
const tokenSessionsListEl = document.querySelector('#token-sessions-list');
const tokenPanelToggleBtnEl = document.querySelector('#token-panel-toggle-btn');
const sessionSelectEl = document.querySelector('#session-select');
const sessionModalEl = document.querySelector('#session-modal');
const sessionModalFormEl = document.querySelector('#session-modal-form');
const sessionModalNameEl = document.querySelector('#session-modal-name');
const sessionModalPathEl = document.querySelector('#session-modal-path');
const sessionModalCloseEl = document.querySelector('#session-modal-close');
const dangerousModeOptionEl = document.querySelector('#dangerous-mode-option');
const dangerousModeInputEl = document.querySelector('#dangerous-mode-input');
const collabControlsEl = document.querySelector('#collab-controls');
const collabRoleBadgeEl = document.querySelector('#collab-role-badge');
const collabStatusEl = document.querySelector('#collab-status');
const requestControlBtnEl = document.querySelector('#request-control-btn');
const transferControlSelectEl = document.querySelector('#transfer-control-select');
const transferControlBtnEl = document.querySelector('#transfer-control-btn');
const collabRequestsEl = document.querySelector('#collab-requests');
const previewPanelEl = document.querySelector('#preview-panel');
const previewFrameEl = document.querySelector('#preview-frame');
const previewStatusEl = document.querySelector('#preview-status');
const previewPortInputEl = document.querySelector('#preview-port-input');
const previewToggleBtnEl = document.querySelector('#preview-toggle-btn');
const previewOpenBtnEl = document.querySelector('#preview-open-btn');
const previewCloseBtnEl = document.querySelector('#preview-close-btn');
const apiKeyModalEl = document.querySelector('#api-key-modal');
const apiKeyModalFormEl = document.querySelector('#api-key-modal-form');
const apiKeyModalInputEl = document.querySelector('#api-key-modal-input');
const apiKeyModalTitleEl = document.querySelector('#api-key-modal-title');
const apiKeyProviderEls = document.querySelectorAll('input[name="api-key-provider"]');
const apiKeyProviderFieldEl = document.querySelector('#api-key-provider-field');
const apiKeyModalLabelEl = document.querySelector('#api-key-modal-label');
const apiKeyModalHintEl = document.querySelector('#api-key-modal-hint');
const apiKeyModalCloseEl = document.querySelector('#api-key-modal-close');
const accountSummaryEl = document.querySelector('#account-summary');
const accountNameEl = document.querySelector('#account-name');
const signOutBtnEl = document.querySelector('#sign-out-btn');

let term = null;
let fitAddon = null;
let fitFrame = 0;
let observedTerminalSize = '';
let tokenRefreshTimer = null;
let sessionRefreshTimer = null;
let collabRefreshTimer = null;
/** @type {WebSocket | null} */
let socket = null;
let reconnectTimer = null;
let lastSessionSelection = '';
let selectedTokenSessions = [];
const sessionRootByName = {};
const sessionDetailsByName = {};
let allSessions = [];
let tokenSessionsModalContext = { type: 'create', token: null };
let tokenSessionsModalSelected = [];
let apiKeyModalAfterSave = null;

if (agentJobsLinkEl) agentJobsLinkEl.href = `agent-jobs${window.location.search || ''}`;
let apiKeyModalDismissed = false;
let currentCollabState = null;
let terminalOutputBuffer = '';
let currentClaudeAuthLink = '';
let terminalTmuxCopyModeActive = false;
let controllerTerminalSize = null;
const terminalOutputDecoder = new TextDecoder();
const CLAUDE_API_KEY_STORAGE_KEY = 'i3ClaudeCodeApiKey';
const CLAUDE_PROVIDER_STORAGE_KEY = 'i3ClaudeCodeProvider';
const GLM_API_KEY_STORAGE_KEY = 'i3ClaudeCodeGlmApiKey';
const OPENAI_API_KEY_STORAGE_KEY = 'i3CodexOpenAiApiKey';
const TERMINAL_WHEEL_LINE_HEIGHT = 32;
const TERMINAL_WHEEL_MAX_LINES = 12;

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

function renderAccountSummary() {
  if (!accountSummaryEl || session.authType !== 'firebase') return;
  const label = session.displayName || session.email || 'Google account';
  if (accountNameEl) accountNameEl.textContent = label;
  accountSummaryEl.classList.remove('hidden');
}

async function signOutFirebaseSession() {
  try {
    await fetch(apiPath('/api/auth/logout'), {
      method: 'POST',
      credentials: 'include',
    });
  } finally {
    window.location.reload();
  }
}

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

function getStoredClaudeProvider() {
  try {
    return localStorage.getItem(CLAUDE_PROVIDER_STORAGE_KEY) === 'glm' ? 'glm' : 'anthropic';
  } catch {
    return 'anthropic';
  }
}

function getSelectedSessionDetails() {
  const name = getSelectedSession();
  return sessionDetailsByName[name] || { name, agent: 'claude', provider: getStoredClaudeProvider() };
}

function getStoredClaudeApiKey(provider = getStoredClaudeProvider()) {
  try {
    const storageKey = provider === 'openai'
      ? OPENAI_API_KEY_STORAGE_KEY
      : (provider === 'glm' ? GLM_API_KEY_STORAGE_KEY : CLAUDE_API_KEY_STORAGE_KEY);
    return localStorage.getItem(storageKey) || '';
  } catch {
    return '';
  }
}

function setStoredClaudeCredentials(provider, value) {
  try {
    const normalizedProvider = ['glm', 'openai'].includes(provider) ? provider : 'anthropic';
    const storageKey = normalizedProvider === 'openai'
      ? OPENAI_API_KEY_STORAGE_KEY
      : (normalizedProvider === 'glm' ? GLM_API_KEY_STORAGE_KEY : CLAUDE_API_KEY_STORAGE_KEY);
    localStorage.setItem(CLAUDE_PROVIDER_STORAGE_KEY, normalizedProvider);
    if (value) localStorage.setItem(storageKey, value);
  } catch {
    // Ignore browsers that block localStorage.
  }
}

function updateApiKeyModalForProvider() {
  const details = getSelectedSessionDetails();
  const selectedProvider = document.querySelector('input[name="api-key-provider"]:checked')?.value;
  const provider = details.agent === 'codex' ? 'openai' : (selectedProvider === 'glm' ? 'glm' : 'anthropic');
  const isCodex = provider === 'openai';
  dangerousModeOptionEl?.classList.toggle('hidden', isCodex);
  if (apiKeyModalTitleEl) apiKeyModalTitleEl.textContent = isCodex ? 'OpenAI Codex API key' : 'Claude Code API key';
  if (apiKeyModalLabelEl) apiKeyModalLabelEl.textContent = isCodex ? 'OpenAI API key' : (provider === 'glm' ? 'GLM API key' : 'Anthropic API key');
  if (apiKeyModalInputEl) {
    apiKeyModalInputEl.placeholder = isCodex ? 'sk-proj-...' : (provider === 'glm' ? 'Enter your Z.AI API key' : 'sk-ant-...');
    apiKeyModalInputEl.value = getStoredClaudeApiKey(provider);
  }
  if (apiKeyModalHintEl) {
    apiKeyModalHintEl.textContent = isCodex
      ? 'The key is used to sign this session into Codex and is isolated from other Codex sessions.'
      : (provider === 'glm'
        ? 'Claude Code will connect to GLM through the Z.AI Anthropic-compatible endpoint.'
        : 'This key is saved in this browser and sent only when starting a Claude Code session.');
  }
}

function isApiKeyModalOpen() {
  return Boolean(apiKeyModalEl && !apiKeyModalEl.classList.contains('hidden'));
}

function openApiKeyModal(options = {}) {
  if (!apiKeyModalEl) return;
  if (isApiKeyModalOpen()) {
    // Session polling can request this modal every few seconds. Preserve the
    // user's provider choice and partially-entered key while it is already open.
    if (typeof options.afterSave === 'function') apiKeyModalAfterSave = options.afterSave;
    return;
  }
  apiKeyModalDismissed = false;
  apiKeyModalAfterSave = typeof options.afterSave === 'function' ? options.afterSave : null;
  const details = getSelectedSessionDetails();
  const isCodex = details.agent === 'codex';
  apiKeyProviderFieldEl?.classList.toggle('hidden', isCodex);
  if (!isCodex) {
    const preferredProvider = getStoredClaudeProvider();
    const preferredRadio = document.querySelector(`input[name="api-key-provider"][value="${preferredProvider}"]`);
    if (preferredRadio) preferredRadio.checked = true;
  }
  if (dangerousModeInputEl) dangerousModeInputEl.checked = !isCodex && details.dangerousMode === true;
  updateApiKeyModalForProvider();
  apiKeyModalEl.classList.remove('hidden');
  setTimeout(() => apiKeyModalInputEl?.focus(), 0);
}

function closeApiKeyModal() {
  if (!apiKeyModalEl) return;
  apiKeyModalEl.classList.add('hidden');
  apiKeyModalAfterSave = null;
  apiKeyModalDismissed = true;
}

async function saveApiKeyFromModal(event) {
  if (event) event.preventDefault();
  const details = getSelectedSessionDetails();
  const selectedProvider = document.querySelector('input[name="api-key-provider"]:checked')?.value;
  const provider = details.agent === 'codex' ? 'openai' : (selectedProvider === 'glm' ? 'glm' : 'anthropic');
  const key = (apiKeyModalInputEl?.value || '').trim();
  if (!key) {
    setTokenStatus(`Enter a ${provider === 'openai' ? 'OpenAI' : (provider === 'glm' ? 'GLM' : 'Claude Code')} API key.`, 'is-error');
    return;
  }
  if (details.agent === 'claude') {
    const settingsResp = await apiFetch(`/api/claudecode/sessions/${encodeURIComponent(details.name)}/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dangerousMode: Boolean(dangerousModeInputEl?.checked) }),
    });
    const settings = await settingsResp.json().catch(() => ({}));
    if (!settingsResp.ok) {
      setTokenStatus(settings.detail || 'Failed to save dangerous mode.', 'is-error');
      return;
    }
    details.dangerousMode = settings.dangerousMode === true;
  }
  setStoredClaudeCredentials(provider, key);
  setTokenStatus(`${provider === 'openai' ? 'OpenAI' : (provider === 'glm' ? 'GLM' : 'Anthropic')} API key saved.`, 'is-success');
  const next = apiKeyModalAfterSave;
  closeApiKeyModal();
  if (next) setTimeout(() => next(), 0);
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

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect(message = 'Control changed, reconnecting…') {
  clearReconnectTimer();
  setConnectionStatus(null, message);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    void connect();
  }, 500);
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

function getPreviewPort() {
  const port = Number.parseInt(previewPortInputEl?.value || '5173', 10);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) return null;
  return port;
}

function previewPathForPort(port) {
  const path = apiPath(`/preview/${String(port)}/`);
  if (!sessionToken) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set('claudecodeToken', sessionToken);
  return `${url.pathname}${url.search}`;
}

function openPreviewPanel() {
  const port = getPreviewPort();
  if (!port) {
    setTokenStatus('Enter a preview port between 1024 and 65535.', 'is-error');
    return;
  }
  const previewPath = previewPathForPort(port);
  if (previewFrameEl) previewFrameEl.src = previewPath;
  if (previewStatusEl) {
    previewStatusEl.textContent = `Previewing localhost:${String(port)} from this VM.`;
  }
  previewPanelEl?.classList.remove('hidden');
  setTokenStatus(`Preview opened for localhost:${String(port)}.`, 'is-success');
}

function closePreviewPanel() {
  previewPanelEl?.classList.add('hidden');
  if (previewFrameEl) previewFrameEl.src = 'about:blank';
}

function openPreviewInNewTab() {
  const port = getPreviewPort();
  if (!port) {
    setTokenStatus('Enter a preview port between 1024 and 65535.', 'is-error');
    return;
  }
  window.open(previewPathForPort(port), '_blank', 'noopener,noreferrer');
}

renderAccountSummary();
signOutBtnEl?.addEventListener('click', () => {
  void signOutFirebaseSession();
});

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
  term.parser?.registerOscHandler?.(52, (data) => {
    const marker = data.indexOf(';');
    if (marker === -1) return false;
    const encoded = data.slice(marker + 1);
    if (!encoded) return false;
    try {
      const copiedText = decodeBase64Utf8(encoded);
      if (copiedText.includes('platform.claude.com/oauth/authorize')) {
        showClaudeAuthLink(copiedText.trim());
      }
      void writeTextToClipboard(copiedText);
      return true;
    } catch {
      return false;
    }
  });
  term.onData((data) => {
    if (!currentCollabState?.isController) return;
    if (socket?.readyState === WebSocket.OPEN) {
      if (terminalTmuxCopyModeActive) {
        terminalTmuxCopyModeActive = false;
        socket.send(JSON.stringify({ type: 'tmux-copy-mode', action: 'cancel' }));
      }
      socket.send(new TextEncoder().encode(data));
    }
  });
  terminalWrapEl?.addEventListener('wheel', handleTerminalWheel, {
    capture: true,
    passive: false,
  });
  scheduleFit();
}

function handleTerminalWheel(event) {
  const delta = event.deltaY;
  if (!delta) return;
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  if (!getSelectedSession()) return;
  const lines = Math.max(
    1,
    Math.min(TERMINAL_WHEEL_MAX_LINES, Math.ceil(Math.abs(delta) / TERMINAL_WHEEL_LINE_HEIGHT))
  );
  terminalTmuxCopyModeActive = true;
  socket.send(
    JSON.stringify({
      type: 'tmux-scroll',
      direction: delta < 0 ? 'up' : 'down',
      lines,
    })
  );
}

function scheduleFit() {
  if (!term || fitFrame) return;
  fitFrame = requestAnimationFrame(() => {
    fitFrame = 0;
    if (!currentCollabState?.isController && controllerTerminalSize) {
      applyControllerTerminalSize();
      return;
    }
    try {
      fitAddon?.fit();
    } catch {
      // ignore
    }
    sendResize();
  });
}

function setTerminalFullscreen(enabled) {
  if (!terminalPanelEl || !terminalFullscreenBtnEl) return;
  terminalPanelEl.classList.toggle('terminal-panel--fullscreen', enabled);
  document.body.classList.toggle('terminal-fullscreen-active', enabled);
  terminalFullscreenBtnEl.textContent = enabled ? 'Exit full screen' : 'Full screen';
  terminalFullscreenBtnEl.setAttribute('aria-pressed', String(enabled));
  terminalFullscreenBtnEl.setAttribute('aria-label', enabled ? 'Exit terminal full screen' : 'Open terminal full screen');
  scheduleFit();
  requestAnimationFrame(scheduleFit);
}

function toggleTerminalFullscreen() {
  setTerminalFullscreen(!terminalPanelEl?.classList.contains('terminal-panel--fullscreen'));
}

function applyControllerTerminalSize() {
  if (!term || !controllerTerminalSize) return;
  if (term.cols === controllerTerminalSize.cols && term.rows === controllerTerminalSize.rows) return;
  try {
    term.resize(controllerTerminalSize.cols, controllerTerminalSize.rows);
  } catch {
    // ignore
  }
}

function sendResize() {
  if (!socket || socket.readyState !== WebSocket.OPEN || !term) return;
  if (!currentCollabState?.isController) return;
  socket.send(
    JSON.stringify({
      type: 'resize',
      cols: term.cols,
      rows: term.rows,
    })
  );
}

function disconnect() {
  clearReconnectTimer();
  if (socket) {
    socket.close();
    socket = null;
  }
  setConnectionButton('connect');
  setConnectionStatus('offline', 'Disconnected');
}

function stripTerminalControlSequences(text) {
  return text
    .replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');
}

function showClaudeAuthLink(link) {
  currentClaudeAuthLink = link;
  if (terminalAuthLinkUrlEl) terminalAuthLinkUrlEl.textContent = link;
  terminalAuthLinkEl?.classList.remove('hidden');
}

function hideClaudeAuthLink() {
  currentClaudeAuthLink = '';
  terminalAuthLinkEl?.classList.add('hidden');
  if (terminalAuthLinkUrlEl) terminalAuthLinkUrlEl.textContent = '';
}

function detectClaudeAuthLink(text) {
  const cleaned = stripTerminalControlSequences(text);
  terminalOutputBuffer = `${terminalOutputBuffer}${cleaned}`.slice(-12000);
  const match = terminalOutputBuffer.match(/https:\/\/platform\.claude\.com\/oauth\/authorize\?[^\s"'<>]+/);
  if (!match) return;
  const link = match[0].replace(/[),.;]+$/, '');
  if (link && link !== currentClaudeAuthLink) showClaudeAuthLink(link);
}

function decodeBase64Utf8(value) {
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

async function connect() {
  clearReconnectTimer();
  disconnect();
  ensureTerm();
  term.reset();
  controllerTerminalSize = null;
  terminalOutputBuffer = '';
  hideClaudeAuthLink();

  const selected = getSelectedSession();
  if (!selected) {
    setConnectionStatus('offline', 'Select a session before connecting');
    setConnectionButton('connect');
    return;
  }

  await loadCollabState();
  const details = getSelectedSessionDetails();
  const provider = details.agent === 'codex' ? 'openai' : getStoredClaudeProvider();
  const agent = details.agent;
  const apiKey = getStoredClaudeApiKey(provider);
  if (!apiKey && isPrivilegedRole(session.role) && currentCollabState?.isController !== false) {
    setConnectionStatus('offline', 'Enter Claude Code API key');
    setConnectionButton('connect');
    openApiKeyModal({ afterSave: connect });
    return;
  }

  setConnectionStatus(null, 'Connecting…');
  setConnectionButton('disconnect');

  const ws = new WebSocket(wsUrl());
  socket = ws;
  ws.binaryType = 'arraybuffer';
  let wsOpened = false;

  ws.onopen = () => {
    wsOpened = true;
    let startPayload = { type: 'start' };
    startPayload.session = selected;
    if (apiKey) {
      startPayload.provider = provider;
      startPayload.agent = agent;
      startPayload.api_key = apiKey;
    }
    const rootDir = sessionRootByName[selected];
    if (rootDir) startPayload.rootDir = rootDir;
    ws.send(JSON.stringify(startPayload));
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
        } else if (msg.type === 'collab' && msg.state) {
          currentCollabState = msg.state;
          if (msg.state.isController) {
            controllerTerminalSize = null;
            scheduleFit();
          } else {
            applyControllerTerminalSize();
          }
          renderCollabState(msg.state);
          setConnectionStatus(msg.state.isController ? 'online' : null, msg.state.isController ? 'Connected as controller' : 'Connected as viewer');
        } else if (msg.type === 'terminal-size') {
          const cols = Number(msg.cols);
          const rows = Number(msg.rows);
          if (Number.isFinite(cols) && Number.isFinite(rows)) {
            controllerTerminalSize = { cols, rows };
            if (!currentCollabState?.isController) {
              applyControllerTerminalSize();
            }
          }
        }
      } catch {
        // ignore non-JSON text
      }
      return;
    }
    const view = new Uint8Array(event.data);
    detectClaudeAuthLink(terminalOutputDecoder.decode(view, { stream: true }));
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
    if (ev.code === 4409) {
      scheduleReconnect();
      return;
    }
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

function stopCollabAutoRefresh() {
  if (collabRefreshTimer) {
    clearInterval(collabRefreshTimer);
    collabRefreshTimer = null;
  }
}

function startCollabAutoRefresh() {
  stopCollabAutoRefresh();
  collabRefreshTimer = window.setInterval(() => {
    void loadCollabState();
  }, 3000);
}

function selectedSessionPath(path) {
  const selected = getSelectedSession();
  if (!selected) return '';
  return `/api/claudecode/sessions/${encodeURIComponent(selected)}${path}`;
}

async function loadCollabState() {
  const path = selectedSessionPath('/collab');
  if (!path) {
    currentCollabState = null;
    renderCollabState(null);
    return null;
  }
  const response = await apiFetch(path);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    currentCollabState = null;
    renderCollabState(null, payload.detail || 'Control state unavailable.');
    return null;
  }
  const wasController = Boolean(currentCollabState?.isController);
  currentCollabState = payload;
  renderCollabState(payload);
  if (socket?.readyState === WebSocket.OPEN && wasController !== Boolean(payload.isController)) {
    disconnect();
    scheduleReconnect();
  }
  return payload;
}

function renderCollabState(state, fallbackMessage = '') {
  if (!collabControlsEl || !collabStatusEl) return;
  if (!state) {
    if (collabRoleBadgeEl) {
      collabRoleBadgeEl.textContent = 'No session';
      collabRoleBadgeEl.className = 'collab-role-badge';
    }
    collabStatusEl.textContent = fallbackMessage || 'Select a session to view control state.';
    requestControlBtnEl?.classList.add('hidden');
    transferControlSelectEl?.classList.add('hidden');
    transferControlBtnEl?.classList.add('hidden');
    collabRequestsEl?.classList.add('hidden');
    return;
  }

  const controller = state.controllerLabel || 'Unknown';
  const master = state.masterLabel || 'Unknown';
  const role = state.isMaster
    ? (state.isController ? 'Master, controlling' : 'Master')
    : (state.isController ? 'Controller' : 'Viewer');
  const pendingForMe = (state.pendingRequests || []).some((request) => request.actorId === state.actorId);
  collabStatusEl.textContent = `Controller: ${controller}. Master: ${master}.`;

  if (collabRoleBadgeEl) {
    collabRoleBadgeEl.textContent = pendingForMe && !state.isController && !state.isMaster ? 'Request pending' : role;
    collabRoleBadgeEl.className = `collab-role-badge ${roleClassName(state, pendingForMe)}`.trim();
  }

  if (requestControlBtnEl) {
    requestControlBtnEl.classList.toggle('hidden', Boolean(state.isController || state.isMaster));
    requestControlBtnEl.disabled = pendingForMe;
    requestControlBtnEl.textContent = pendingForMe ? 'Request sent' : 'Request control';
  }

  const transferCandidates = (state.participants || []).slice();
  if (state.isMaster && state.actorId && state.actorId !== state.controllerId) {
    transferCandidates.unshift({
      actorId: state.actorId,
      label: `${state.actorLabel || 'Me'} (me)`,
    });
  }
  const seenTransferCandidates = new Set();
  const transferable = transferCandidates
    .filter((p) => p.actorId && p.actorId !== state.controllerId)
    .filter((p) => {
      if (seenTransferCandidates.has(p.actorId)) return false;
      seenTransferCandidates.add(p.actorId);
      return true;
    });
  if (transferControlSelectEl && transferControlBtnEl) {
    const showTransfer = Boolean(state.isMaster && transferable.length);
    transferControlSelectEl.classList.toggle('hidden', !showTransfer);
    transferControlBtnEl.classList.toggle('hidden', !showTransfer);
    transferControlSelectEl.innerHTML = '';
    for (const participant of transferable) {
      transferControlSelectEl.appendChild(new Option(participant.label || participant.actorId, participant.actorId));
    }
  }

  if (collabRequestsEl) {
    const requests = state.isMaster ? (state.pendingRequests || []) : [];
    collabRequestsEl.classList.toggle('hidden', requests.length === 0);
    collabRequestsEl.innerHTML = requests
      .map((request) => `
        <span>${escapeHtml(request.label || request.actorId || 'Viewer')} requested control</span>
        <button class="ghost-button" type="button" data-approve-control="${escapeHtml(request.actorId || '')}">Approve</button>
      `)
      .join('');
    collabRequestsEl.querySelectorAll('[data-approve-control]').forEach((button) => {
      button.addEventListener('click', () => {
        void approveControl(button.getAttribute('data-approve-control') || '');
      });
    });
  }
}

function roleClassName(state, pendingForMe) {
  if (pendingForMe && !state.isController && !state.isMaster) return 'is-pending';
  if (state.isMaster && state.isController) return 'is-master-controller';
  if (state.isMaster) return 'is-master';
  if (state.isController) return 'is-controller';
  return 'is-viewer';
}

async function requestControl() {
  const path = selectedSessionPath('/request-control');
  if (!path) return;
  const response = await apiFetch(path, { method: 'POST' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setTokenStatus(payload.detail || 'Failed to request control.', 'is-error');
    return;
  }
  currentCollabState = payload;
  renderCollabState(payload);
  setConnectionStatus(null, 'Control request sent');
  setTokenStatus('Control request sent.', 'is-success');
}

async function approveControl(actorId) {
  const path = selectedSessionPath('/approve-control');
  if (!path || !actorId) return;
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actorId }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setTokenStatus(payload.detail || 'Failed to approve control.', 'is-error');
    return;
  }
  currentCollabState = payload;
  renderCollabState(payload);
  scheduleReconnect('Control transferred, reconnecting…');
  setTokenStatus('Control transferred.', 'is-success');
}

async function transferControl() {
  const path = selectedSessionPath('/transfer-control');
  const actorId = transferControlSelectEl?.value || '';
  if (!path || !actorId) return;
  const label = transferControlSelectEl?.selectedOptions?.[0]?.textContent || '';
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actorId, label }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setTokenStatus(payload.detail || 'Failed to transfer control.', 'is-error');
    return;
  }
  currentCollabState = payload;
  renderCollabState(payload);
  scheduleReconnect('Control transferred, reconnecting…');
  setTokenStatus('Control transferred.', 'is-success');
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

async function writeTextToClipboard(text) {
  const writeWithFallbackField = () => {
    const fallbackField = document.createElement('textarea');
    fallbackField.value = text;
    fallbackField.setAttribute('readonly', 'readonly');
    fallbackField.style.position = 'fixed';
    fallbackField.style.top = '0';
    fallbackField.style.left = '0';
    fallbackField.style.width = '1px';
    fallbackField.style.height = '1px';
    fallbackField.style.opacity = '0';
    document.body.appendChild(fallbackField);
    fallbackField.focus();
    fallbackField.select();
    fallbackField.setSelectionRange(0, fallbackField.value.length);

    try {
      return document.execCommand('copy');
    } finally {
      document.body.removeChild(fallbackField);
    }
  };

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Embedded pages can reject async clipboard writes; keep the user gesture
      // alive and try the legacy copy path before reporting failure.
    }
  }

  if (writeWithFallbackField()) return true;
  throw new Error('Clipboard copy was rejected by the browser.');
}

async function copyToken(token) {
  const link = getShareableTokenLink(token);
  try {
    await writeTextToClipboard(link);
    setTokenStatus('Shareable link copied to clipboard.', 'is-success');
  } catch (error) {
    console.warn('Failed to copy token link:', error);
    setTokenStatus('Could not copy the shareable link. Please copy it manually.', 'is-error');
  }
}

terminalAuthLinkCopyEl?.addEventListener('click', async () => {
  if (!currentClaudeAuthLink) return;
  try {
    await writeTextToClipboard(currentClaudeAuthLink);
    setTokenStatus('Claude sign-in link copied.', 'is-success');
  } catch {
    setTokenStatus('Could not copy Claude sign-in link. Select the link text manually.', 'is-error');
  }
});

terminalAuthLinkOpenEl?.addEventListener('click', () => {
  if (!currentClaudeAuthLink) return;
  window.open(currentClaudeAuthLink, '_blank', 'noopener,noreferrer');
});

function getShareableTokenLink(token) {
  const basePath = window.location.pathname.startsWith('/claudecode') ? '/claudecode/' : '/';
  const url = new URL(basePath, window.location.origin);
  url.searchParams.set('claudecodeToken', token);
  return url.toString();
}

async function copyShareableTokenLink(token) {
  const link = getShareableTokenLink(token);
  try {
    await writeTextToClipboard(link);
    setTokenStatus('Shareable link copied to clipboard.', 'is-success');
  } catch (error) {
    console.warn('Failed to copy shareable token link:', error);
    setTokenStatus('Could not copy the shareable link. Please copy it manually.', 'is-error');
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
  const shareableLink = getShareableTokenLink(tokenInfo.token || '');
  tokenResultEl.classList.remove('hidden');
  tokenResultEl.innerHTML = `
    <p class="token-result__title">New guest token created</p>
    <p class="token-result__meta">Access: <strong>${escapeHtml(tokenInfo.accessType || 'viewer')}</strong> · TTL: <strong>${escapeHtml(ttlText)}</strong></p>
    <div class="token-result__token">
      <span>${escapeHtml(shareableLink)}</span>
      <button class="ghost-button token-result__copy-button" type="button" data-copy-link="${escapeHtml(tokenInfo.token || '')}">Copy link</button>
    </div>
    <p class="token-result__meta">This link is shown once. Copy it now if you need to share it later.</p>
  `;

  const copyLinkButton = tokenResultEl.querySelector('[data-copy-link]');
  if (copyLinkButton) {
    copyLinkButton.addEventListener('click', () => {
      void copyShareableTokenLink(copyLinkButton.getAttribute('data-copy-link') || '');
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
      const isOwnerToken = String(tokenInfo.role || '').toLowerCase() === 'owner';
      const canRevoke = !isRevoked && !isOwnerToken;
      const ttlText = tokenInfo.ttlSeconds ? `${tokenInfo.ttlSeconds}s` : 'no expiry';
      const badge = isRevoked ? 'Revoked' : tokenInfo.accessType || 'viewer';
      const revokeTitle = isOwnerToken
        ? 'Owner tokens cannot be revoked.'
        : isRevoked
          ? 'Token is already revoked.'
          : 'Revoke token';
      const sessionValue = String(tokenInfo.session || '*');
      const sessionMode = sessionValue === '*' ? 'all' : 'specific';
      const sessionSummary = sessionMode === 'all'
        ? 'All sessions'
        : 'Specific sessions';
      const sessionEditor = isOwnerToken
        ? ''
        : `
            <div class="token-session-editor">
              <select data-token-session-mode="${escapeHtml(tokenInfo.token || '')}">
                <option value="all" ${sessionMode === 'all' ? 'selected' : ''}>All sessions</option>
                <option value="specific" ${sessionMode === 'specific' ? 'selected' : ''}>Specific sessions</option>
              </select>
              <button class="ghost-button" type="button" data-token-session-edit="${escapeHtml(tokenInfo.token || '')}" ${sessionMode === 'specific' ? '' : 'disabled'}>Edit</button>
            </div>
        `;
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
          <div class="token-card__meta">
            <span>Sessions: <strong>${escapeHtml(sessionSummary)}</strong></span>
            ${sessionEditor}
          </div>
          <div class="token-card__actions">
            <button class="ghost-button" type="button" data-copy-token="${escapeHtml(tokenInfo.token || '')}">Copy</button>
            <button class="ghost-button" type="button" data-revoke-token="${escapeHtml(tokenInfo.token || '')}" ${canRevoke ? '' : 'disabled'} title="${escapeHtml(revokeTitle)}">Revoke</button>
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

  tokenListEl.querySelectorAll('[data-token-session-mode]').forEach((select) => {
    select.addEventListener('change', () => {
      const token = select.getAttribute('data-token-session-mode') || '';
      if (!token) return;
      if (select.value === 'specific') {
        openTokenSessionsModalForToken(token);
      } else {
        void updateTokenSessions(token, []);
      }
    });
  });

  tokenListEl.querySelectorAll('[data-token-session-edit]').forEach((button) => {
    button.addEventListener('click', () => {
      const token = button.getAttribute('data-token-session-edit') || '';
      if (!token) return;
      openTokenSessionsModalForToken(token);
    });
  });

  // Attach records for lookup
  const cards = Array.from(tokenListEl.querySelectorAll('.token-card'));
  cards.forEach((card, index) => {
    card.__tokenRecord = tokens[index];
  });
}

function getSelectedSession() {
  const value = sessionSelectEl?.value;
  if (!value || value === '__create__') return '';
  return value;
}

function updateDangerousModeVisibility() {
  const isClaude = document.querySelector('input[name="session-agent"]:checked')?.value !== 'codex';
  dangerousModeOptionEl?.classList.toggle('hidden', !isClaude);
  if (!isClaude && dangerousModeInputEl) dangerousModeInputEl.checked = false;
}

function openSessionModal() {
  if (!sessionModalEl) return;
  updateDangerousModeVisibility();
  sessionModalEl.classList.remove('hidden');
  sessionModalNameEl?.focus();
}

function closeSessionModal() {
  if (!sessionModalEl) return;
  sessionModalEl.classList.add('hidden');
  if (sessionModalFormEl) sessionModalFormEl.reset();
  if (sessionSelectEl && lastSessionSelection) {
    sessionSelectEl.value = lastSessionSelection;
  }
}

function openTokenSessionsModal() {
  if (!tokenSessionsModalEl) return;
  tokenSessionsModalEl.classList.remove('hidden');
  tokenSessionsListEl?.focus();
}

function closeTokenSessionsModal() {
  if (!tokenSessionsModalEl) return;
  tokenSessionsModalEl.classList.add('hidden');
  if (tokenSessionsModalFormEl) tokenSessionsModalFormEl.reset();
}

async function loadSessions() {
  setTokenStatus('Loading sessions…', '');
  const resp = await apiFetch('/api/claudecode/sessions');
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    setTokenStatus(payload.detail || 'Failed to load sessions.', 'is-error');
    return [];
  }
  allSessions = payload.sessions || [];
  Object.keys(sessionDetailsByName).forEach((name) => delete sessionDetailsByName[name]);
  Object.assign(sessionDetailsByName, payload.sessionDetails || {});
  renderSessionSelect(payload.sessions || []);
  renderTokenSessionOptions(payload.sessions || []);
  const selected = getSelectedSession();
  if (selected && !allSessions.includes(selected)) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      disconnect();
      setConnectionStatus('offline', 'Disconnected (session access removed)');
    }
    if (sessionSelectEl) sessionSelectEl.value = '';
    lastSessionSelection = '';
  }
  setTokenStatus(`Loaded ${String((payload.sessions || []).length)} session(s).`, 'is-success');
  const selectedDetails = getSelectedSessionDetails();
  const selectedProvider = selectedDetails.agent === 'codex' ? 'openai' : getStoredClaudeProvider();
  if (isPrivilegedRole(session.role)
      && getSelectedSession()
      && !getStoredClaudeApiKey(selectedProvider)
      && !apiKeyModalDismissed
      && !isApiKeyModalOpen()) {
    openApiKeyModal();
  }
  await loadCollabState();
  return payload.sessions || [];
}

function renderSessionSelect(sessions) {
  if (!sessionSelectEl) return;
  const current = sessionSelectEl.value;
  sessionSelectEl.innerHTML = '';
  sessionSelectEl.appendChild(new Option('Select a session…', '', true, false));
  if (isPrivilegedRole(session.role)) {
    sessionSelectEl.appendChild(new Option('Create a new session', '__create__'));
  }
  const sorted = (sessions || []).slice().sort();
  for (const s of sorted) {
    if (!s) continue;
    const details = sessionDetailsByName[s];
    const suffix = details?.agent === 'codex' ? 'Codex' : (details?.provider === 'glm' ? 'Claude + GLM' : 'Claude');
    sessionSelectEl.appendChild(new Option(`${s} — ${suffix}`, s));
  }
  if (current && current !== '__create__') {
    sessionSelectEl.value = current;
    lastSessionSelection = current;
  } else if (lastSessionSelection) {
    sessionSelectEl.value = lastSessionSelection;
  }
}

function renderTokenSessionOptions(sessions) {
  renderTokenSessionsChecklist(sessions, tokenSessionsModalSelected.length ? tokenSessionsModalSelected : selectedTokenSessions);
}

function renderTokenSessionsChecklist(sessions, selected) {
  if (!tokenSessionsListEl) return;
  const sorted = (sessions || []).slice().sort();
  tokenSessionsListEl.innerHTML = '';
  for (const s of sorted) {
    if (!s || s === '*') continue;
    const label = document.createElement('label');
    label.className = 'session-checkbox';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = s;
    if (selected.includes(s)) checkbox.checked = true;
    const text = document.createElement('span');
    text.textContent = s;
    label.appendChild(checkbox);
    label.appendChild(text);
    tokenSessionsListEl.appendChild(label);
  }
}

function openTokenSessionsModalForToken(token) {
  const record = getTokenRecord(token);
  const sessionValue = record?.session || '*';
  const selected = sessionValue === '*' ? [] : sessionValue.split(',').map((s) => s.trim()).filter(Boolean);
  tokenSessionsModalContext = { type: 'edit', token };
  tokenSessionsModalSelected = selected;
  renderTokenSessionsChecklist(allSessions, selected);
  openTokenSessionsModal();
}

function openTokenSessionsModalForCreate() {
  tokenSessionsModalContext = { type: 'create', token: null };
  tokenSessionsModalSelected = selectedTokenSessions.slice();
  renderTokenSessionsChecklist(allSessions, tokenSessionsModalSelected);
  openTokenSessionsModal();
}

function getTokenRecord(token) {
  if (!tokenListEl) return null;
  const escapeToken = window.CSS?.escape ? CSS.escape(token) : token.replace(/"/g, '\\"');
  const raw = tokenListEl.querySelector(`[data-token-session-mode="${escapeToken}"]`);
  if (!raw) return null;
  return raw.closest('.token-card')?.__tokenRecord || null;
}

async function createSessionFromModal(event) {
  if (event) event.preventDefault();
  const name = (sessionModalNameEl?.value || '').trim();
  const path = (sessionModalPathEl?.value || '').trim() || undefined;
  const agent = document.querySelector('input[name="session-agent"]:checked')?.value === 'codex' ? 'codex' : 'claude';
  const dangerousMode = agent === 'claude' && Boolean(dangerousModeInputEl?.checked);
  if (!name) {
    setTokenStatus('Enter a session name.', 'is-error');
    return;
  }
  setTokenStatus('Creating session…', '');
  const resp = await apiFetch('/api/claudecode/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, path, agent, dangerousMode }),
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    setTokenStatus(payload.detail || 'Failed to create session.', 'is-error');
    return;
  }
  setTokenStatus('Session created.', 'is-success');
  closeSessionModal();
  await loadSessions();
  if (sessionSelectEl) sessionSelectEl.value = name;
  lastSessionSelection = name;
  await loadCollabState();
  if (path) {
    sessionRootByName[name] = path;
  }
  if (isPrivilegedRole(session.role)) {
    openApiKeyModal({ afterSave: connect });
  }
}

function saveTokenSessionsFromModal(event) {
  if (event) event.preventDefault();
  if (!tokenSessionsListEl) return;
  const selected = Array.from(tokenSessionsListEl.querySelectorAll('input[type="checkbox"]'))
    .filter((input) => input.checked)
    .map((input) => input.value);

  if (tokenSessionsModalContext.type === 'edit' && tokenSessionsModalContext.token) {
    void updateTokenSessions(tokenSessionsModalContext.token, selected);
  } else {
    selectedTokenSessions = selected;
  }
  closeTokenSessionsModal();
}

async function updateTokenSessions(token, sessions) {
  if (!token) return;
  const sessionValue = sessions.length === 0 ? '*' : sessions.join(',');
  setTokenStatus('Updating token sessions…', '');
  const resp = await apiFetch(`/api/tokens/${encodeURIComponent(token)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: sessionValue }),
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    setTokenStatus(payload.detail || 'Failed to update token sessions.', 'is-error');
    return;
  }
  setTokenStatus('Token sessions updated.', 'is-success');
  await loadTokens();
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

function stopTokenAutoRefresh() {
  if (tokenRefreshTimer) {
    clearInterval(tokenRefreshTimer);
    tokenRefreshTimer = null;
  }
}

function stopSessionAutoRefresh() {
  if (sessionRefreshTimer) {
    clearInterval(sessionRefreshTimer);
    sessionRefreshTimer = null;
  }
}

function startTokenAutoRefresh() {
  stopTokenAutoRefresh();
  tokenRefreshTimer = window.setInterval(() => {
    void loadTokens();
  }, 3000);
}

function startSessionAutoRefresh() {
  stopSessionAutoRefresh();
  sessionRefreshTimer = window.setInterval(() => {
    void loadSessions();
  }, 3000);
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
    // collect selected sessions from UI
    let sessionValue = undefined;
    try {
      const mode = tokenSessionModeEl?.value || 'all';
      if (mode === 'all') {
        sessionValue = '*';
      } else {
        if (selectedTokenSessions.length === 0) {
          setTokenStatus('Select at least one session for a specific-sessions token.', 'is-error');
          openTokenSessionsModalForCreate();
          return;
        }
        sessionValue = selectedTokenSessions.join(',');
      }
    } catch (e) {
      sessionValue = undefined;
    }

    const response = await apiFetch('/api/tokens', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        accessType,
        ttlSeconds,
        session: sessionValue,
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
    if (tokenSessionModeEl) tokenSessionModeEl.value = 'all';
    selectedTokenSessions = [];
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
  startTokenAutoRefresh();

  if (tokenPanelToggleBtnEl) {
    tokenPanelToggleBtnEl.addEventListener('click', () => {
      const collapsed = tokenManagementPanelEl.classList.toggle('token-panel--collapsed');
      tokenPanelToggleBtnEl.textContent = collapsed ? 'Manage tokens' : 'Hide tokens';
      tokenPanelToggleBtnEl.setAttribute('aria-expanded', String(!collapsed));
      scheduleFit();
    });
  }

  if (createTokenFormEl) {
    createTokenFormEl.addEventListener('submit', (event) => {
      void createGuestToken(event);
    });
  }

  if (sessionModalFormEl) {
    sessionModalFormEl.addEventListener('submit', (ev) => {
      void createSessionFromModal(ev);
    });
  }

  if (sessionModalCloseEl) {
    sessionModalCloseEl.addEventListener('click', () => {
      closeSessionModal();
    });
  }

  if (sessionModalEl) {
    sessionModalEl.addEventListener('click', (ev) => {
      if (ev.target === sessionModalEl) closeSessionModal();
    });
  }

  if (apiKeyModalFormEl) {
    apiKeyModalFormEl.addEventListener('submit', (ev) => {
      void saveApiKeyFromModal(ev);
    });
  }
  apiKeyProviderEls.forEach((radio) => radio.addEventListener('change', updateApiKeyModalForProvider));

  if (apiKeyModalCloseEl) {
    apiKeyModalCloseEl.addEventListener('click', () => {
      closeApiKeyModal();
    });
  }

  if (apiKeyModalEl) {
    apiKeyModalEl.addEventListener('click', (ev) => {
      if (ev.target === apiKeyModalEl) closeApiKeyModal();
    });
  }

  if (tokenSessionModeEl) {
    tokenSessionModeEl.addEventListener('change', () => {
      if (tokenSessionModeEl.value === 'specific') {
        openTokenSessionsModalForCreate();
      } else {
        selectedTokenSessions = [];
      }
    });
  }

  if (tokenSessionsModalFormEl) {
    tokenSessionsModalFormEl.addEventListener('submit', (ev) => {
      void saveTokenSessionsFromModal(ev);
    });
  }

  if (tokenSessionsModalCloseEl) {
    tokenSessionsModalCloseEl.addEventListener('click', () => {
      closeTokenSessionsModal();
    });
  }

  if (tokenSessionsModalEl) {
    tokenSessionsModalEl.addEventListener('click', (ev) => {
      if (ev.target === tokenSessionsModalEl) closeTokenSessionsModal();
    });
  }

  if (refreshTokensBtnEl) {
    refreshTokensBtnEl.addEventListener('click', () => {
      void loadTokens();
    });
  }
}

function initSessionPicker() {
  if (!sessionSelectEl) return;
  sessionSelectEl.addEventListener('change', () => {
    if (sessionSelectEl.value === '__create__') {
      if (isPrivilegedRole(session.role)) {
        openSessionModal();
      } else {
        sessionSelectEl.value = '';
      }
      return;
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
      disconnect();
      setConnectionStatus('offline', 'Disconnected (session changed)');
    }
    lastSessionSelection = sessionSelectEl.value;
    void loadCollabState();
  });
}


window.addEventListener('beforeunload', () => {
  clearReconnectTimer();
  stopTokenAutoRefresh();
  stopSessionAutoRefresh();
  stopCollabAutoRefresh();
});
window.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    if (terminalPanelEl?.classList.contains('terminal-panel--fullscreen')) {
      setTerminalFullscreen(false);
      return;
    }
    closeSessionModal();
    closeTokenSessionsModal();
  }
});

terminalFullscreenBtnEl?.addEventListener('click', toggleTerminalFullscreen);

connectionToggleBtn.addEventListener('click', () => {
  if (connectionToggleBtn.dataset.state === 'disconnect') {
    disconnect();
    return;
  }
  void connect();
});

requestControlBtnEl?.addEventListener('click', () => {
  void requestControl();
});

transferControlBtnEl?.addEventListener('click', () => {
  void transferControl();
});

previewToggleBtnEl?.addEventListener('click', () => {
  openPreviewPanel();
});

previewOpenBtnEl?.addEventListener('click', () => {
  openPreviewInNewTab();
});

previewCloseBtnEl?.addEventListener('click', () => {
  closePreviewPanel();
});

setConnectionButton('connect');
void loadSessions();
startSessionAutoRefresh();
startCollabAutoRefresh();
initSessionPicker();
initTokenManagement();

window.addEventListener('resize', scheduleFit);
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', scheduleFit);
}
if (document.fonts?.ready) {
  void document.fonts.ready.then(scheduleFit);
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

// Do not auto-connect; user must pick a session first.

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}
