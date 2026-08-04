/**
 * Popup: import the CareerAgent-generated profile, tweak it, and trigger a
 * fill on the active tab.
 */

'use strict';

/* global chrome, document, FileReader */

const FIELDS = [
  'fullName',
  'email',
  'phone',
  'linkedin',
  'github',
  'portfolio',
  'location',
];

const AUTO_KEY = 'careeragent_autofill_on_load';

let currentProfile = {};

function readForm() {
  const profile = { ...currentProfile };
  FIELDS.forEach((f) => {
    profile[f] = document.getElementById(f).value.trim();
  });
  // Keep first/last in step with an edited full name.
  const parts = (profile.fullName || '').split(/\s+/).filter(Boolean);
  profile.firstName = parts[0] || '';
  profile.lastName = parts.length > 1 ? parts[parts.length - 1] : '';
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

function renderSummary(profile) {
  const el = document.getElementById('summary');
  if (!profile || !profile.email) {
    el.textContent = 'No profile imported yet.';
    return;
  }
  const resume = profile.resume
    ? `resume: ${profile.resume.filename}`
    : 'no resume attached';
  el.innerHTML =
    `<strong>${profile.fullName || '(no name)'}</strong><br>` +
    `${profile.email}<br><span style="color:#666">${resume}</span>`;
}

async function persist(profile) {
  currentProfile = profile;
  await chrome.runtime.sendMessage({
    type: 'CAREERAGENT_SAVE_PROFILE',
    profile,
  });
  renderSummary(profile);
}

document.addEventListener('DOMContentLoaded', async () => {
  currentProfile =
    (await chrome.runtime.sendMessage({ type: 'CAREERAGENT_GET_PROFILE' })) || {};
  writeForm(currentProfile);
  renderSummary(currentProfile);

  const { [AUTO_KEY]: autoEnabled = true } = await chrome.storage.local.get(AUTO_KEY);
  document.getElementById('autoOnLoad').checked = autoEnabled;

  document.getElementById('autoOnLoad').addEventListener('change', async (e) => {
    await chrome.storage.local.set({ [AUTO_KEY]: e.target.checked });
    setStatus(e.target.checked ? 'Autofill on load enabled.' : 'Autofill on load off.');
  });

  document.getElementById('import').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const parsed = JSON.parse(reader.result);
        if (!parsed || typeof parsed !== 'object' || !parsed.email) {
          setStatus('That file has no email field — is it a CareerAgent profile?');
          return;
        }
        await persist(parsed);
        writeForm(parsed);
        setStatus('Profile imported.');
      } catch (err) {
        setStatus(`Could not read that file: ${err.message}`);
      }
    };
    reader.readAsText(file);
  });

  document.getElementById('save').addEventListener('click', async () => {
    await persist(readForm());
    setStatus('Saved.');
  });

  document.getElementById('fill').addEventListener('click', async () => {
    await persist(readForm());
    try {
      const res = await chrome.runtime.sendMessage({ type: 'CAREERAGENT_TRIGGER_FILL' });
      if (!res) {
        setStatus('No response — open the application page first.');
      } else {
        const attached = res.attached ? `, resume attached` : '';
        setStatus(`Filled ${res.filled} field(s)${attached}. Review, then submit.`);
      }
    } catch (err) {
      setStatus('This page is not a supported application form.');
    }
  });
});
