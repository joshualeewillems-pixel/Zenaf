/* Zenaf Renderer — background service worker.
 *
 * Polls the Zenaf API for render jobs. On a job: opens the URL in an
 * inactive tab, waits for the conversation to render, extracts the text
 * with the same selectors as the bookmarklet, closes the tab, and POSTs
 * the transcript back. Fully autonomous — the user just pastes a link
 * into Zenaf and the agent appears in their review queue.
 */

const POLL_MS = 15000;
const RENDER_WAIT_MS = 12000;

async function cfg() {
  const s = await chrome.storage.sync.get({
    apiBase: 'https://zenaf-staging.fly.dev',
    workerId: 'desktop-' + Math.random().toString(36).slice(2, 8),
  });
  s.apiBase = (s.apiBase || '').replace(/\/+$/, '');
  return s;
}

function extractInPage() {
  const nodes = document.querySelectorAll('[data-message-author-role]');
  const out = [];
  nodes.forEach((n) => {
    const role = n.getAttribute('data-message-author-role');
    const label = role === 'user' ? 'USER' : role === 'assistant' ? 'ASSISTANT' : String(role).toUpperCase();
    const text = (n.innerText || '').trim();
    if (text) out.push(label + ': ' + text);
  });
  let transcript;
  if (out.length) {
    transcript = out.join('\n\n');
  } else {
    const main = document.querySelector('main') || document.querySelector('article') || document.body;
    transcript = ((main && main.innerText) || '').trim();
  }
  return { transcript: transcript.slice(0, 60000), title: document.title || '' };
}

async function renderJob(apiBase, job) {
  const tab = await chrome.tabs.create({ url: job.url, active: false });
  try {
    // Wait for the page to render the conversation.
    await new Promise((r) => setTimeout(r, RENDER_WAIT_MS));
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractInPage,
    });
    const { transcript, title } = res.result || {};
    if (!transcript || transcript.length < 50) {
      throw new Error('no conversation text extracted');
    }
    const r = await fetch(`${apiBase}/agents/render-jobs/${job.id}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, title }),
    });
    if (!r.ok) throw new Error('complete failed: ' + r.status);
    console.log('[zenaf] rendered job', job.id);
  } catch (e) {
    await fetch(`${apiBase}/agents/render-jobs/${job.id}/fail`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: String((e && e.message) || e) }),
    }).catch(() => {});
    console.warn('[zenaf] job failed', job.id, e);
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function poll() {
  try {
    const { apiBase, workerId } = await cfg();
    const r = await fetch(
      `${apiBase}/agents/render-jobs/next?worker_id=${encodeURIComponent(workerId)}`
    );
    if (!r.ok) return;
    const { job } = await r.json();
    if (job && job.url) {
      await renderJob(apiBase, job);
    }
  } catch (e) {
    // Offline / API down — try again next poll.
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('zenaf-poll', { periodInMinutes: 0.25 });
});
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === 'zenaf-poll') poll();
});
// Kick off promptly on startup too.
poll();
