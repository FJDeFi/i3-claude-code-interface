const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#prompt-form");
const inputEl = document.querySelector("#prompt-input");
const sendButtonEl = document.querySelector("#send-button");
const clearButtonEl = document.querySelector("#clear-chat");
const newChatButtonEl = document.querySelector("#new-chat");
const serverStatusEl = document.querySelector("#server-status");
const statusDotEl = document.querySelector("#status-dot");
const apiKeyInputEl = document.querySelector("#api-key-input");

const STORAGE_KEY = "claude-tmux-chat-id";

let state = {
  chatId: null,
  eventSource: null,
  assistantNode: null,
  assistantBuffer: "",
  lastEventId: 0,
};

function setConnectionStatus(kind, label) {
  statusDotEl.classList.remove("online", "offline");
  if (kind === "online") statusDotEl.classList.add("online");
  if (kind === "offline") statusDotEl.classList.add("offline");
  serverStatusEl.textContent = label;
}

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "You" : role === "status" ? "···" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const label = document.createElement("p");
  label.className = "message-label";
  label.textContent =
    role === "user" ? "You" : role === "status" ? "System" : "Assistant";

  const body = document.createElement("pre");
  body.className = "message-body";
  body.textContent = text;

  bubble.append(label, body);
  article.append(avatar, bubble);
  messagesEl.append(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  return { article, body };
}

function ensureAssistantNode() {
  if (!state.assistantNode) {
    state.assistantNode = appendMessage("assistant", "");
    state.assistantBuffer = "";
  }
  return state.assistantNode;
}

function finalizeAssistantNode() {
  state.assistantNode = null;
  state.assistantBuffer = "";
}

function closeStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function openStream(chatId) {
  closeStream();
  const url = `/chats/${chatId}/events?after_id=${state.lastEventId || 0}`;
  const source = new EventSource(url);
  state.eventSource = source;

  const handleEvent = (role) => (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    if (payload.id) state.lastEventId = payload.id;

    if (role === "user") {
      finalizeAssistantNode();
      appendMessage("user", payload.content);
    } else if (role === "assistant") {
      const node = ensureAssistantNode();
      state.assistantBuffer += payload.content;
      node.body.textContent = state.assistantBuffer;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } else if (role === "status") {
      finalizeAssistantNode();
      appendMessage("status", payload.content);
    } else if (role === "error") {
      finalizeAssistantNode();
      appendMessage("status", `error: ${payload.content}`);
    }
  };

  source.addEventListener("user", handleEvent("user"));
  source.addEventListener("assistant", handleEvent("assistant"));
  source.addEventListener("status", handleEvent("status"));
  source.addEventListener("error", handleEvent("error"));
  source.addEventListener("end", () => {
    setConnectionStatus("offline", "Chat ended");
    closeStream();
  });

  source.onopen = () => setConnectionStatus("online", `chat ${chatId}`);
  source.onerror = () => setConnectionStatus("offline", "Reconnecting...");
}

async function createChat() {
  const apiKey = (apiKeyInputEl.value || "").trim();
  if (!apiKey) {
    apiKeyInputEl.focus();
    throw new Error("Please provide an ANTHROPIC_API_KEY before starting a chat.");
  }

  setConnectionStatus(null, "Starting tmux session...");
  const response = await fetch("/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ anthropic_api_key: apiKey }),
  });
  if (!response.ok) {
    setConnectionStatus("offline", "Failed to create chat");
    let detail = response.status;
    try {
      const payload = await response.json();
      if (payload?.detail) detail = payload.detail;
    } catch {
      // ignore
    }
    throw new Error(`Failed to create chat: ${detail}`);
  }
  const payload = await response.json();
  state.chatId = payload.chat_id;
  state.lastEventId = 0;
  finalizeAssistantNode();
  localStorage.setItem(STORAGE_KEY, state.chatId);
  // Clear the key from the DOM once the chat is created; the server now
  // owns it for the chat lifetime and the browser no longer needs it.
  apiKeyInputEl.value = "";
  openStream(state.chatId);
  return state.chatId;
}

async function ensureChat() {
  if (state.chatId) return state.chatId;
  return await createChat();
}

async function sendPrompt(text) {
  const chatId = await ensureChat();
  const response = await fetch(`/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.detail || `send failed (${response.status})`);
  }
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;

  inputEl.value = "";
  sendButtonEl.disabled = true;

  try {
    await sendPrompt(text);
  } catch (err) {
    appendMessage("status", err.message || "Unknown error");
  } finally {
    sendButtonEl.disabled = false;
    inputEl.focus();
  }
});

newChatButtonEl.addEventListener("click", async () => {
  messagesEl.innerHTML = "";
  try {
    await createChat();
    appendMessage("status", `New tmux chat ${state.chatId} created`);
  } catch (err) {
    appendMessage("status", err.message || "Failed to start chat");
  }
});

clearButtonEl.addEventListener("click", () => {
  messagesEl.innerHTML = "";
  finalizeAssistantNode();
});

async function resumeChatIfAny() {
  const existing = localStorage.getItem(STORAGE_KEY);
  if (!existing) {
    setConnectionStatus(null, "Press 'New chat' to begin");
    return;
  }
  try {
    const response = await fetch(`/chats/${existing}`);
    if (!response.ok) {
      localStorage.removeItem(STORAGE_KEY);
      setConnectionStatus(null, "Press 'New chat' to begin");
      return;
    }
    const payload = await response.json();
    state.chatId = existing;
    (payload.events || []).forEach((ev) => {
      state.lastEventId = Math.max(state.lastEventId, ev.id);
      if (ev.role === "user") appendMessage("user", ev.content);
      else if (ev.role === "assistant") {
        const node = ensureAssistantNode();
        state.assistantBuffer += ev.content;
        node.body.textContent = state.assistantBuffer;
      } else if (ev.role === "status") appendMessage("status", ev.content);
    });
    finalizeAssistantNode();
    if (payload.chat?.status === "running") {
      openStream(existing);
    } else {
      setConnectionStatus("offline", "Previous chat ended");
    }
  } catch (err) {
    console.error(err);
    setConnectionStatus("offline", "Failed to resume chat");
  }
}

function scrollActivePromptIntoView() {
  const active = document.activeElement;
  if (active !== inputEl && active !== apiKeyInputEl) return;
  requestAnimationFrame(() => {
    active.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
}

inputEl.addEventListener("focus", scrollActivePromptIntoView);
apiKeyInputEl.addEventListener("focus", scrollActivePromptIntoView);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", scrollActivePromptIntoView);
}

resumeChatIfAny();
