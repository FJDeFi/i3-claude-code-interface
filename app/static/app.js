const POLL_INTERVAL_MS = 1000;

const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#prompt-form");
const inputEl = document.querySelector("#prompt-input");
const sendButtonEl = document.querySelector("#send-button");
const clearButtonEl = document.querySelector("#clear-chat");
const helperTextEl = document.querySelector("#helper-text");
const serverStatusEl = document.querySelector("#server-status");
const statusDotEl = document.querySelector("#status-dot");

function addMessage(role, text, meta = "") {
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "You" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const label = document.createElement("p");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Assistant";

  const body = document.createElement("p");
  body.textContent = text;

  bubble.append(label, body);

  if (meta) {
    const metaLine = document.createElement("p");
    metaLine.className = "helper-text";
    metaLine.textContent = meta;
    bubble.append(metaLine);
  }

  article.append(avatar, bubble);
  messagesEl.append(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  return { article, body };
}

function setComposerState(isBusy, message) {
  sendButtonEl.disabled = isBusy;
  inputEl.disabled = isBusy;
  helperTextEl.textContent = message;
}

function setConnectionStatus(kind, label) {
  statusDotEl.classList.remove("online", "offline");
  if (kind === "online") {
    statusDotEl.classList.add("online");
  } else if (kind === "offline") {
    statusDotEl.classList.add("offline");
  }
  serverStatusEl.textContent = label;
}

async function pollJob(jobId, responseNode) {
  while (true) {
    const response = await fetch(`/result/${jobId}`);

    if (!response.ok) {
      throw new Error(`Result lookup failed with status ${response.status}.`);
    }

    const payload = await response.json();
    const status = payload.status;

    if (status === "done") {
      responseNode.textContent = payload.result || "No result returned.";
      setConnectionStatus("online", "Connected");
      return;
    }

    if (status === "failed") {
      responseNode.textContent = payload.result || "Job failed without details.";
      setConnectionStatus("offline", "Last job failed");
      return;
    }

    responseNode.textContent =
      status === "running"
        ? "The worker is processing your request..."
        : "Prompt submitted. Waiting for a worker to claim the job...";

    await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

async function checkServer() {
  try {
    const response = await fetch("/");
    if (!response.ok) {
      throw new Error(`Unexpected status ${response.status}`);
    }
    setConnectionStatus("online", "Connected");
  } catch (error) {
    console.error(error);
    setConnectionStatus("offline", "Unable to reach server");
  }
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();

  const prompt = inputEl.value.trim();
  if (!prompt) {
    return;
  }

  addMessage("user", prompt);
  const pendingMessage = addMessage(
    "assistant",
    "Submitting your prompt...",
    "A job will be created on the server."
  );

  inputEl.value = "";
  setComposerState(true, "Submitting prompt and waiting for the server...");

  try {
    const response = await fetch(`/prompt?prompt=${encodeURIComponent(prompt)}`, {
      method: "POST",
    });

    if (!response.ok) {
      throw new Error(`Submit failed with status ${response.status}.`);
    }

    const payload = await response.json();
    pendingMessage.body.textContent = "Job accepted. Polling for the result...";
    await pollJob(payload.job_id, pendingMessage.body);
  } catch (error) {
    console.error(error);
    pendingMessage.body.textContent =
      error instanceof Error ? error.message : "An unexpected error occurred.";
    setConnectionStatus("offline", "Request failed");
  } finally {
    setComposerState(false, "The UI will poll for completion automatically.");
    inputEl.focus();
  }
});

clearButtonEl.addEventListener("click", () => {
  messagesEl.innerHTML = "";
  addMessage(
    "assistant",
    "Conversation cleared. Send another prompt when you're ready."
  );
});

checkServer();
