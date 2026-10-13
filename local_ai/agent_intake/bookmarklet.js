/* Zenaf Share-Link Bookmarklet
 *
 * INSTALL: Create a new bookmark in your phone/desktop browser, name it
 * "Send to Zenaf", and paste the ENTIRE minified line from the bottom of
 * this file as the URL.
 *
 * USE: Open a ChatGPT or Claude public share link in your browser, tap the
 * "Send to Zenaf" bookmark. It extracts the conversation and sends it to
 * your Zenaf intake — no highlighting, no copy/paste.
 *
 * First run asks for your Zenaf URL (default: staging). Saved in localStorage.
 */
(function () {
  'use strict';

  var DEFAULT_API = 'https://zenaf-staging.fly.dev';

  function apiBase() {
    var saved = null;
    try { saved = localStorage.getItem('zenaf_api_base'); } catch (e) {}
    if (saved) return saved;
    var v = prompt('Zenaf URL:', DEFAULT_API);
    v = (v || DEFAULT_API).trim().replace(/\/+$/, '');
    try { localStorage.setItem('zenaf_api_base', v); } catch (e) {}
    return v;
  }

  function toast(msg) {
    var d = document.createElement('div');
    d.textContent = msg;
    d.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);' +
      'background:#1a1a2e;color:#fff;padding:12px 20px;border-radius:12px;z-index:999999;' +
      'font:14px system-ui;box-shadow:0 4px 20px rgba(0,0,0,.4);max-width:90vw;text-align:center;';
    document.body.appendChild(d);
    setTimeout(function () { d.remove(); }, 6000);
  }

  /* --- extraction --- */

  function extractChatGPT() {
    // data-message-author-role is the stable hook on share pages.
    var nodes = document.querySelectorAll('[data-message-author-role]');
    if (!nodes.length) return null;
    var out = [];
    nodes.forEach(function (n) {
      var role = n.getAttribute('data-message-author-role');
      var label = role === 'user' ? 'USER' : role === 'assistant' ? 'ASSISTANT' : role.toUpperCase();
      var text = (n.innerText || '').trim();
      if (text) out.push(label + ': ' + text);
    });
    return out.length ? out.join('\n\n') : null;
  }

  function extractClaude() {
    // Claude share pages: look for message groups; fall back to article/main text.
    var out = [];
    var candidates = document.querySelectorAll('[data-testid*="message"], .message, [class*="message-"]');
    if (candidates.length) {
      candidates.forEach(function (n, i) {
        var text = (n.innerText || '').trim();
        if (text && text.length > 10) out.push((i % 2 === 0 ? 'USER' : 'ASSISTANT') + ': ' + text);
      });
      if (out.length) return out.join('\n\n');
    }
    return null;
  }

  function extractGeneric() {
    var main = document.querySelector('main') || document.querySelector('article') || document.body;
    var text = (main.innerText || '').trim();
    // Strip nav/chrome noise: keep lines with substance.
    var lines = text.split('\n').map(function (l) { return l.trim(); })
      .filter(function (l) { return l.length > 0; });
    return lines.join('\n');
  }

  function extract() {
    var url = location.href;
    var transcript =
      extractChatGPT() ||
      extractClaude() ||
      extractGeneric();
    return { url: url, transcript: transcript, title: document.title };
  }

  /* --- send --- */

  function send() {
    toast('Reading conversation…');
    var data = extract();
    if (!data.transcript || data.transcript.length < 50) {
      toast('Could not find conversation text on this page.');
      return;
    }
    var base = apiBase();
    toast('Sending to Zenaf… (' + data.transcript.length + ' chars)');
    fetch(base + '/agents/connect/share-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: data.url,
        title: data.title,
        transcript: data.transcript.slice(0, 60000),
      }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j.agent) {
          var n = (res.j.mined && res.j.mined.projects || []).length;
          toast('Sent to Zenaf: "' + (res.j.agent.name || 'agent') + '"' +
            (n ? ' + ' + n + ' project proposal' + (n > 1 ? 's' : '') : '') +
            '. Check your review queue.');
        } else {
          toast('Zenaf error: ' + ((res.j && res.j.detail) || 'unknown'));
        }
      })
      .catch(function (e) {
        toast('Could not reach Zenaf: ' + e.message);
      });
  }

  send();
})();
