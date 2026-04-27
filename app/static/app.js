const statusDotEl = document.querySelector("#status-dot");
const serverStatusEl = document.querySelector("#server-status");
const terminalWrapEl = document.querySelector("#terminal-wrap");
const connectBtn = document.querySelector("#connect-btn");
const disconnectBtn = document.querySelector("#disconnect-btn");
const apiKeyInput = document.querySelector("#anthropic-api-key");

let term = null;
let fitAddon = null;
/** @type {WebSocket | null} */
let socket = null;

function setConnectionStatus(kind, label) {
  statusDotEl.classList.remove("online", "offline");
  if (kind === "online") statusDotEl.classList.add("online");
  if (kind === "offline") statusDotEl.classList.add("offline");
  serverStatusEl.textContent = label;
}

function wsUrl() {
  const loc = window.location;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${loc.host}/ws/terminal`;
}

function ensureTerm() {
  if (term) return;
  term = new Terminal({
    cursorBlink: true,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 14,
    theme: {
      background: "#050817",
      foreground: "#f4f7ff",
      cursor: "#40d7ff",
      selectionBackground: "#27346f",
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
  requestAnimationFrame(() => {
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
      type: "resize",
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
  connectBtn.disabled = false;
  apiKeyInput.disabled = false;
  disconnectBtn.disabled = true;
  setConnectionStatus("offline", "Disconnected");
}

function connect() {
  const anthropicApiKey = apiKeyInput.value.trim();
  if (!anthropicApiKey) {
    setConnectionStatus("offline", "Enter an Anthropic API key");
    apiKeyInput.focus();
    return;
  }

  disconnect();
  ensureTerm();
  term.reset();

  setConnectionStatus(null, "Connecting…");
  connectBtn.disabled = true;
  apiKeyInput.disabled = true;
  disconnectBtn.disabled = false;

  const ws = new WebSocket(wsUrl());
  socket = ws;
  ws.binaryType = "arraybuffer";
  let wsOpened = false;

  ws.onopen = () => {
    wsOpened = true;
    ws.send(
      JSON.stringify({
        type: "start",
        anthropic_api_key: anthropicApiKey,
      })
    );
    setConnectionStatus("online", "Connected");
    scheduleFit();
  };

  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "error" && msg.message) {
          term.writeln(`\r\n\x1b[31m${msg.message}\x1b[0m\r\n`);
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
      "WebSocket error (browsers hide details). Check DevTools → Network → WS for /ws/terminal, or Console for mixed-content / CSP."
    );
    setConnectionStatus("offline", "WebSocket error — see browser console");
  };

  ws.onclose = (ev) => {
    if (socket === ws) socket = null;
    connectBtn.disabled = false;
    apiKeyInput.disabled = false;
    disconnectBtn.disabled = true;
    const reason = ev.reason ? `: ${ev.reason}` : "";
    const detail = `code ${ev.code}${reason}`;
    if (!wsOpened) {
      setConnectionStatus("offline", `WebSocket failed (${detail})`);
    } else if (ev.code === 1000) {
      setConnectionStatus("offline", "Disconnected");
    } else {
      setConnectionStatus("offline", `Disconnected (${detail})`);
    }
  };
}

connectBtn.addEventListener("click", () => connect());
disconnectBtn.addEventListener("click", () => disconnect());

window.addEventListener("resize", scheduleFit);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", scheduleFit);
}
