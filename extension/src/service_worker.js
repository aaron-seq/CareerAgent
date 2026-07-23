/**
 * Background service worker: owns the profile in chrome.storage.local and
 * relays a fill request to the active tab. PII stays in the browser.
 */

'use strict';

/* global chrome */

const PROFILE_KEY = 'careeragent_profile';

async function getProfile() {
  const data = await chrome.storage.local.get(PROFILE_KEY);
  return data[PROFILE_KEY] || {};
}

async function saveProfile(profile) {
  await chrome.storage.local.set({ [PROFILE_KEY]: profile });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === 'CAREERAGENT_GET_PROFILE') {
      sendResponse(await getProfile());
    } else if (msg.type === 'CAREERAGENT_SAVE_PROFILE') {
      await saveProfile(msg.profile);
      sendResponse({ ok: true });
    } else if (msg.type === 'CAREERAGENT_TRIGGER_FILL') {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const profile = await getProfile();
      const res = await chrome.tabs.sendMessage(tab.id, {
        type: 'CAREERAGENT_FILL',
        profile,
      });
      sendResponse(res);
    }
  })();
  return true; // keep the message channel open for the async response
});
