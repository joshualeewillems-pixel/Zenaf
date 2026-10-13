// "Send to Zenaf" — iOS Shortcut JavaScript (Run JavaScript on Web Page)
// Paste this into the Shortcut's JavaScript action. It extracts the
// conversation and calls completion() with a dictionary; the next
// Shortcut action POSTs it to Zenaf via Get Contents of URL.

(function () {
  var nodes = document.querySelectorAll('[data-message-author-role]');
  var out = [];
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    var role = n.getAttribute('data-message-author-role');
    var label = role === 'user' ? 'USER' : role === 'assistant' ? 'ASSISTANT' : String(role).toUpperCase();
    var text = (n.innerText || '').trim();
    if (text) out.push(label + ': ' + text);
  }
  var transcript;
  if (out.length) {
    transcript = out.join('\n\n');
  } else {
    var main = document.querySelector('main') || document.querySelector('article') || document.body;
    transcript = ((main && main.innerText) || '').trim();
  }
  completion({
    url: location.href,
    title: document.title || 'shared conversation',
    transcript: transcript.slice(0, 60000)
  });
})();
