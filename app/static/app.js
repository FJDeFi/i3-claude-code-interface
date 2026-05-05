const statusDotEl = document.querySelector("#status-dot");
const serverStatusEl = document.querySelector("#server-status");
const terminalWrapEl = document.querySelector("#terminal-wrap");
const connectionToggleBtn = document.querySelector("#connection-toggle-btn");

let term = null;
let fitAddon = null;
let fitFrame = 0;
let observedTerminalSize = "";
/** @type {WebSocket | null} */
let socket = null;

function isEmbedMode() {
  try {
    const p = new URLSearchParams(window.location.search);
    if (p.has("embed")) return true;
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
  document.documentElement.classList.toggle("embed", embed);
  document.body.classList.toggle("embed", embed);
  return embed;
}

const embedded = applyEmbedClass();

function setConnectionStatus(kind, label) {
  statusDotEl.classList.remove("online", "offline");
  if (kind === "online") statusDotEl.classList.add("online");
  if (kind === "offline") statusDotEl.classList.add("offline");
  serverStatusEl.textContent = label;
}

function setConnectionButton(state) {
  const isDisconnect = state === "disconnect";
  connectionToggleBtn.textContent = isDisconnect ? "Disconnect" : "Connect";
  connectionToggleBtn.dataset.state = isDisconnect ? "disconnect" : "connect";
  connectionToggleBtn.classList.toggle("ghost-button", isDisconnect);
  connectionToggleBtn.classList.toggle("primary-button", !isDisconnect);
  connectionToggleBtn.disabled = false;
}

function wsUrl() {
  const loc = window.location;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  const basePath = loc.pathname.startsWith("/claudecode") ? "/claudecode" : "";
  return `${scheme}://${loc.host}${basePath}/ws/terminal`;
}

function ensureTerm() {
  if (term) return;
  term = new Terminal({
    cursorBlink: true,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 14,
    theme: {
      background: "#fffaf2",
      foreground: "#1f1a14",
      cursor: "#ff7a1a",
      selectionBackground: "#ffd7ad",
      black: "#1f1a14",
      blue: "#e85d04",
      brightBlue: "#ff7a1a",
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
  setConnectionButton("connect");
  setConnectionStatus("offline", "Disconnected");
}

function connect() {
  disconnect();
  ensureTerm();
  term.reset();

  setConnectionStatus(null, "Connecting…");
  setConnectionButton("disconnect");

  const ws = new WebSocket(wsUrl());
  socket = ws;
  ws.binaryType = "arraybuffer";
  let wsOpened = false;

  ws.onopen = () => {
    wsOpened = true;
    ws.send(JSON.stringify({ type: "start" }));
    setConnectionStatus("online", "Starting Claude Code");
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
    if (socket !== ws) return;
    if (socket === ws) socket = null;
    setConnectionButton("connect");
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

connectionToggleBtn.addEventListener("click", () => {
  if (connectionToggleBtn.dataset.state === "disconnect") {
    disconnect();
    return;
  }
  connect();
});

setConnectionButton("connect");

window.addEventListener("resize", scheduleFit);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", scheduleFit);
}

if (terminalWrapEl && typeof ResizeObserver !== "undefined") {
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
