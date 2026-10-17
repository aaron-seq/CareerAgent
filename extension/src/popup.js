/**
 * Popup: import/edit the saved profile and trigger a fill on the active tab.
 */

'use strict';

/* global chrome, document, module, require */

const mapping =
  typeof module !== 'undefined' && module.exports
    ? require('./field_mapping.js')
    : globalThis.CareerAgentFieldMapping;

const FIELDS = ['fullName', 'email', 'phone', 'linkedin', 'github', 'portfolio', 'location'];
const MAX_TEXT_ANSWER = 5000;

// The stored profile, including `answers`/`resume`, which have no form inputs
// and must survive an edit-and-save of the seven visible fields.
let currentProfile = {};

function readForm() {
  const edits = {};
  FIELDS.forEach((f) => {
    edits[f] = document.getElementById(f).value.trim();
  });
  return edits;
}

function writeForm(profile) {
  FIELDS.forEach((f) => {
    document.getElementById(f).value = (profile && profile[f]) || '';
  });
}

function setStatus(text) {
  document.getElementById('status').textContent = text;
}

/** Apply the visible-field edits without dropping imported answers/resume. */
function withEdits(stored, edits) {
  const next = { ...(stored || {}) };
  FIELDS.forEach((f) => {
    next[f] = typeof edits[f] === 'string' ? edits[f] : '';
  });
  return next;
}

/** Keep only known answer keys with the right type; demographics need consent. */
function parseAnswers(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const answers = {};
  mapping.BOOLEAN_ANSWER_KEYS.forEach((k) => {
    if (typeof raw[k] === 'boolean') answers[k] = raw[k];
  });
  const country = raw[mapping.AUTHORIZATION_COUNTRY_KEY];
  if (typeof country === 'string' && country.trim()) {
    answers[mapping.AUTHORIZATION_COUNTRY_KEY] = country.trim().slice(0, 100);
  }
  const consent = raw[mapping.CONSENT_KEY] === true;
  const textKeys = consent
    ? [...mapping.TEXT_ANSWER_KEYS, ...mapping.DEMOGRAPHIC_ANSWER_KEYS]
    : mapping.TEXT_ANSWER_KEYS;
  textKeys.forEach((k) => {
    if (typeof raw[k] === 'string' && raw[k].trim()) {
      answers[k] = raw[k].trim().slice(0, MAX_TEXT_ANSWER);
    }
  });
  if (consent && mapping.DEMOGRAPHIC_ANSWER_KEYS.some((k) => k in answers)) {
    answers[mapping.CONSENT_KEY] = true;
  }
  return Object.keys(answers).length ? answers : null;
}

/**
 * Parse the profile JSON the CareerAgent app exports (facade.extension_profile).
 *
 * Only known fields are taken, so a pasted blob that happens to carry extra
 * keys (a whole CVProfile, say) can't smuggle anything into storage. The
 * optional `answers` and `resume` blocks are whitelisted key-by-key and only
 * present in the result when the export carried valid ones.
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
  const answers = parseAnswers(parsed.answers);
  if (answers) profile.answers = answers;
  const resume = mapping.validateResume(parsed.resume);
  if (resume) profile.resume = resume;
  return profile;
}

/** One-line summary of what an import carried. */
function importSummary(profile) {
  const parts = ['Imported from CareerAgent'];
  const count = profile.answers
    ? Object.keys(profile.answers).filter(
        (k) => k !== mapping.CONSENT_KEY && k !== mapping.AUTHORIZATION_COUNTRY_KEY
      ).length
    : 0;
  if (count) parts.push(`${count} screening answer(s)`);
  if (profile.resume) parts.push(`resume ${profile.resume.filename}`);
  return `${parts.join(', ')}.`;
}

/** The status line after a fill; always ends with the human's next step. */
function fillSummary(res) {
  if (!res) return 'No response. Open the application page first.';
  const parts = [`Filled ${res.filled || 0} field(s)`];
  if (res.answered) parts.push(`answered ${res.answered} question(s)`);
  if (res.attached) parts.push('attached your resume');
  let text = `${parts.join(', ')}.`;
  const needs = Array.isArray(res.needsYou) ? res.needsYou.length : 0;
  if (needs) text += ` ${needs} question(s) need your answer (outlined in amber).`;
  return `${text} Review everything, then submit yourself.`;
}

// Guarded so `node --test` can require this file for the parse tests;
// in the popup `document` always exists and the listener registers.
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', async () => {
    currentProfile =
      (await chrome.runtime.sendMessage({ type: 'CAREERAGENT_GET_PROFILE' })) || {};
    writeForm(currentProfile);

    async function persist(profile) {
      currentProfile = profile;
      await chrome.runtime.sendMessage({ type: 'CAREERAGENT_SAVE_PROFILE', profile });
    }

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
      await persist(imported);
      document.getElementById('importJson').value = '';
      setStatus(importSummary(imported));
    });

    document.getElementById('save').addEventListener('click', async () => {
      await persist(withEdits(currentProfile, readForm()));
      setStatus('Profile saved.');
    });

    document.getElementById('fill').addEventListener('click', async () => {
      await persist(withEdits(currentProfile, readForm()));
      let res;
      try {
        res = await chrome.runtime.sendMessage({ type: 'CAREERAGENT_TRIGGER_FILL' });
      } catch (err) {
        res = null;
      }
      setStatus(fillSummary(res));
    });
  });
}

// Exported for `node --test`; harmless in the extension (no CommonJS there).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseImport, withEdits, importSummary, fillSummary, FIELDS };
}
