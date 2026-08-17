const session = window.__CLAUDE_CODE_SESSION__ || {};
const jobsListEl = document.querySelector('#jobs-list');
const jobsStatusEl = document.querySelector('#jobs-status');
const newJobBtnEl = document.querySelector('#new-job-btn');
const refreshJobsBtnEl = document.querySelector('#refresh-jobs-btn');
const jobModalEl = document.querySelector('#job-modal');
const jobModalCloseEl = document.querySelector('#job-modal-close');
const jobFormEl = document.querySelector('#job-form');
const submitJobBtnEl = document.querySelector('#submit-job-btn');
const jobFilesEl = document.querySelector('#job-files');
const jobFileListEl = document.querySelector('#job-file-list');
const jobLogModalEl = document.querySelector('#job-log-modal');
const jobLogTitleEl = document.querySelector('#job-log-title');
const jobLogEl = document.querySelector('#job-log');
const jobLogCloseEl = document.querySelector('#job-log-close');
const terminalPageLinkEl = document.querySelector('#terminal-page-link');

let jobs = [];

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderSelectedFiles() {
  jobFileListEl.innerHTML = '';
  const files = Array.from(jobFilesEl.files || []);
  jobFileListEl.classList.toggle('hidden', files.length === 0);
  for (const file of files) {
    const item = document.createElement('li');
    const details = document.createElement('span');
    details.className = 'job-file-list__details';
    const name = document.createElement('strong');
    name.textContent = file.name;
    const size = document.createElement('small');
    size.textContent = formatFileSize(file.size);
    details.append(name, size);
    item.appendChild(details);
    jobFileListEl.appendChild(item);
  }
}

function currentToken() {
  if (session.token) return String(session.token);
  return new URLSearchParams(window.location.search).get('claudecodeToken') || '';
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = currentToken();
  if (token) headers.set('X-Claude-Code-Token', token);
  return fetch(path, { ...options, headers, credentials: 'include' });
}

function setStatus(message, kind = '') {
  jobsStatusEl.textContent = message;
  jobsStatusEl.className = `token-status ${kind}`.trim();
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function actionButton(label, primary, handler) {
  const button = document.createElement('button');
  button.className = primary ? 'primary-button' : 'ghost-button';
  button.type = 'button';
  button.textContent = label;
  button.addEventListener('click', handler);
  return button;
}

function renderJobs() {
  jobsListEl.innerHTML = '';
  if (!jobs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No jobs yet. Submit a small test job to start the worker.';
    jobsListEl.appendChild(empty);
    return;
  }
  for (const job of jobs) {
    const card = document.createElement('article');
    card.className = 'job-card';
    const summary = document.createElement('div');
    summary.className = 'job-card__summary';
    const heading = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = job.name;
    const meta = document.createElement('p');
    meta.textContent = `${job.id} · Created ${formatDate(job.createdAt)} · ${(job.files || []).length} file(s)`;
    heading.append(title, meta);
    const badge = document.createElement('span');
    badge.className = `job-status job-status--${job.status}`;
    badge.textContent = job.status;
    summary.append(heading, badge);

    const actions = document.createElement('div');
    actions.className = 'job-card__actions';
    actions.appendChild(actionButton('View log', false, () => void showLog(job)));
    if (job.status === 'queued' || job.status === 'running') {
      actions.appendChild(actionButton('Cancel', false, () => void cancelJob(job.id)));
    }
    if (job.status === 'completed') {
      actions.appendChild(actionButton('Download result', true, () => void downloadResult(job)));
    }
    card.appendChild(summary);
    if (job.error) {
      const error = document.createElement('p');
      error.className = 'job-card__error';
      error.textContent = job.error;
      card.appendChild(error);
    }
    card.appendChild(actions);
    jobsListEl.appendChild(card);
  }
}

async function loadJobs(showMessage = false) {
  try {
    const response = await apiFetch('api/agent-jobs');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Could not load jobs');
    jobs = payload.jobs || [];
    renderJobs();
    if (showMessage) setStatus('Job list refreshed.', 'is-success');
  } catch (error) {
    setStatus(error.message || 'Could not load jobs.', 'is-error');
  }
}

async function submitJob(event) {
  event.preventDefault();
  submitJobBtnEl.disabled = true;
  submitJobBtnEl.textContent = 'Submitting…';
  try {
    const response = await apiFetch('api/agent-jobs', { method: 'POST', body: new FormData(jobFormEl) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Could not submit job');
    jobModalEl.classList.add('hidden');
    jobFormEl.reset();
    renderSelectedFiles();
    setStatus(`Job ${payload.id} queued.`, 'is-success');
    await loadJobs();
  } catch (error) {
    setStatus(error.message || 'Could not submit job.', 'is-error');
  } finally {
    submitJobBtnEl.disabled = false;
    submitJobBtnEl.textContent = 'Submit job';
  }
}

async function showLog(job) {
  jobLogTitleEl.textContent = `${job.name} · log`;
  jobLogEl.textContent = 'Loading…';
  jobLogModalEl.classList.remove('hidden');
  const response = await apiFetch(`api/agent-jobs/${encodeURIComponent(job.id)}/log`);
  const payload = await response.json().catch(() => ({}));
  jobLogEl.textContent = response.ok ? (payload.log || 'No output yet.') : (payload.detail || 'Could not load log.');
  jobLogEl.scrollTop = jobLogEl.scrollHeight;
}

async function cancelJob(jobId) {
  const response = await apiFetch(`api/agent-jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  const payload = await response.json().catch(() => ({}));
  setStatus(response.ok ? `Job ${jobId} cancelled.` : (payload.detail || 'Could not cancel job.'), response.ok ? 'is-success' : 'is-error');
  await loadJobs();
}

async function downloadResult(job) {
  const response = await apiFetch(`api/agent-jobs/${encodeURIComponent(job.id)}/result`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    setStatus(payload.detail || 'Could not download result.', 'is-error');
    return;
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `agent-job-${job.id}-result.zip`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

newJobBtnEl.addEventListener('click', () => jobModalEl.classList.remove('hidden'));
jobModalCloseEl.addEventListener('click', () => jobModalEl.classList.add('hidden'));
jobLogCloseEl.addEventListener('click', () => jobLogModalEl.classList.add('hidden'));
refreshJobsBtnEl.addEventListener('click', () => void loadJobs(true));
jobFormEl.addEventListener('submit', (event) => void submitJob(event));
jobFilesEl.addEventListener('change', renderSelectedFiles);
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  jobModalEl.classList.add('hidden');
  jobLogModalEl.classList.add('hidden');
});

terminalPageLinkEl.href = `./${window.location.search || ''}`;
void loadJobs();
const pollTimer = window.setInterval(() => void loadJobs(), 2000);
window.addEventListener('beforeunload', () => window.clearInterval(pollTimer));
