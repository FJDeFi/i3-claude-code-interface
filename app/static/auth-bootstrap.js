const authStatus = document.querySelector('#auth-status');
let exchanging = false;

function setAuthStatus(message) {
  if (authStatus) authStatus.textContent = message;
}

function requestParentAuthentication() {
  if (window.parent === window) {
    setAuthStatus('Open this page from your Intelligence3 VM dashboard, or use a guest access link.');
    return;
  }
  window.parent.postMessage({ type: 'i3:claudecode-auth-ready' }, '*');
}

window.addEventListener('message', async (event) => {
  const payload = event.data || {};
  if (payload.type !== 'i3:claudecode-firebase-auth' || exchanging) return;
  if (event.source !== window.parent) return;

  const idToken = String(payload.idToken || '').trim();
  if (!idToken) {
    setAuthStatus('Google login is required before opening Claude Code.');
    return;
  }

  exchanging = true;
  setAuthStatus('Verifying your Google account…');
  try {
    const response = await fetch('api/auth/firebase', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idToken }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail || 'Authentication failed');
    }
    setAuthStatus('Signed in. Opening Claude Code…');
    window.location.reload();
  } catch (error) {
    setAuthStatus(error?.message || 'Could not sign in to Claude Code.');
    exchanging = false;
  }
});

window.addEventListener('DOMContentLoaded', requestParentAuthentication);
window.setTimeout(requestParentAuthentication, 800);
