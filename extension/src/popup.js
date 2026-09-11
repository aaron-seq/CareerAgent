/**
 * Popup: edit the saved profile and trigger a fill on the active tab.
 */

'use strict';

/* global chrome, document, module */

const FIELDS = ['fullName', 'email', 'phone', 'linkedin', 'github', 'portfolio', 'location'];

function readForm() {
  const profile = {};
  FIELDS.forEach((f) => {
    profile[f] = document.getElementById(f).value.trim();
  });
  return profile;
}

function writeForm(profile) {
  FIELDS.forEach((f) => {
    document.getElementById(f).value = (profile && profile[f]) || '';
  });
}

function setStatus(text) {
  document.getElementById('status').textContent = text;
}

/**
 * Parse the profile JSON the CareerAgent app exports.
 *
 * Only the known fields are taken, so a pasted blob that happens to carry
 * extra keys (a whole CVProfile, say) can't smuggle anything into storage.
 * Throws on anything that isn't a JSON object.
 */
function parseImport(text) {
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('expected a JSON object');
  }
  const profile = {};
  FIELDS.forEach((f) => {
    profile[f] = typeof parsed[f] === 'string' ? parsed[f].trim() : '';
  });
  return profile;
}

// Guarded so `node --test` can require this file for the parse tests;
// in the popup `document` always exists and the listener registers.
if (typeof document !== 'undefined') {
document.addEventListener('DOMContentLoaded', async () => {
  const profile = await chrome.runtime.sendMessage({ type: 'CAREERAGENT_GET_PROFILE' });
  writeForm(profile);

  document.getElementById('import').addEventListener('click', async () => {
    const raw = document.getElementById('importJson').value.trim();
    if (!raw) return;
    let imported;
    try {
      imported = parseImport(raw);
    } catch (err) {
      setStatus(`Could not read that JSON: ${err.message}`);
      return;
    }
    writeForm(imported);
    await chrome.runtime.sendMessage({ type: 'CAREERAGENT_SAVE_PROFILE', profile: imported });
    setStatus('Imported from CareerAgent.');
  });

  document.getElementById('save').addEventListener('click', async () => {
    await chrome.runtime.sendMessage({ type: 'CAREERAGENT_SAVE_PROFILE', profile: readForm() });
    setStatus('Profile saved.');
  });

  document.getElementById('fill').addEventListener('click', async () => {
    await chrome.runtime.sendMessage({ type: 'CAREERAGENT_SAVE_PROFILE', profile: readForm() });
    const res = await chrome.runtime.sendMessage({ type: 'CAREERAGENT_TRIGGER_FILL' });
    setStatus(res ? `Filled ${res.filled} field(s). Review, then submit.` : 'No response.');
  });
});
}

// Exported for `node --test`; harmless in the extension (no CommonJS there).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseImport, FIELDS };
}
