/**
 * Popup: edit the saved profile and trigger a fill on the active tab.
 */

'use strict';

/* global chrome, document */

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

document.addEventListener('DOMContentLoaded', async () => {
  const profile = await chrome.runtime.sendMessage({ type: 'CAREERAGENT_GET_PROFILE' });
  writeForm(profile);

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
