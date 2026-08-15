/**
 * Field mapping: given a form field's signals, decide which profile key fills
 * it. This is the testable heart of the autofill extension -- pure functions,
 * no DOM, no chrome APIs, so it runs under `node --test`.
 *
 * Detection is layered by reliability (highest first):
 *   1. HTML `autocomplete` attribute (spec tokens)
 *   2. ARIA label / associated <label>
 *   3. name / id fuzzy match
 *   4. placeholder text
 *
 * The extension NEVER submits a form; it only fills. A human reviews and
 * clicks submit.
 */

'use strict';

// Canonical profile keys we know how to fill.
const PROFILE_KEYS = [
  'firstName',
  'lastName',
  'fullName',
  'email',
  'phone',
  'linkedin',
  'github',
  'portfolio',
  'location',
];

// autocomplete spec token -> profile key.
const AUTOCOMPLETE_MAP = {
  'given-name': 'firstName',
  'additional-name': null,
  'family-name': 'lastName',
  name: 'fullName',
  email: 'email',
  tel: 'phone',
  'tel-national': 'phone',
  url: 'portfolio',
  'address-level2': 'location',
  'country-name': 'location',
};

// Ordered keyword rules for the fuzzy layers. First match wins, so more
// specific rules (first/last name) precede generic ones (name).
const KEYWORD_RULES = [
  { key: 'firstName', any: ['first name', 'firstname', 'given name', 'givenname', 'fname'] },
  { key: 'lastName', any: ['last name', 'lastname', 'family name', 'surname', 'lname'] },
  { key: 'email', any: ['email', 'e-mail'] },
  { key: 'phone', any: ['phone', 'mobile', 'telephone', 'tel'] },
  { key: 'linkedin', any: ['linkedin'] },
  { key: 'github', any: ['github'] },
  // Deliberately no bare "url" here: real ATS forms have several "<service>
  // URL" fields (LinkedIn URL, GitHub URL, Twitter URL, Portfolio URL...);
  // matching on "url" alone stole unrelated ones (e.g. "Twitter URL", seen
  // on a real live Lever form) since it's checked before any service-less
  // fallback. "portfolio"/"website" are specific enough signals on their own.
  { key: 'portfolio', any: ['portfolio', 'website', 'personal site'] },
  { key: 'location', any: ['location', 'city', 'address'] },
  { key: 'fullName', any: ['full name', 'fullname', 'your name', 'name'] },
];

function normalize(text) {
  return (text || '').toString().trim().toLowerCase();
}

// For fuzzy matching, treat any run of non-alphanumeric characters (_ - : .
// * etc.) as a space, so "given_name", "given-name", and "Phone:" all match
// on plain words ("given name", "phone").
function normalizeForFuzzy(text) {
  return normalize(text).replace(/[^a-z0-9]+/g, ' ').trim();
}

// Word/phrase-boundary substring check. Plain `.includes()` false-positives
// on short keywords hiding inside unrelated words -- e.g. rule keyword "tel"
// (for phone) matching inside a label like "...complete the Constellation
// application form" (seen on a real live Greenhouse posting). Both sides are
// pre-normalized to single-space-separated words, so padding with spaces and
// checking for " phrase " gives a cheap exact word/phrase match.
function includesWord(haystack, phrase) {
  return phrase !== '' && (' ' + haystack + ' ').includes(' ' + phrase + ' ');
}

/**
 * @param {object} field - {autocomplete, id, name, label, ariaLabel, placeholder, type}
 * @returns {string|null} a profile key, or null if unknown
 */
function mapFieldToProfileKey(field) {
  if (!field) return null;

  // 1. autocomplete attribute (most reliable).
  const ac = normalize(field.autocomplete);
  if (ac && Object.prototype.hasOwnProperty.call(AUTOCOMPLETE_MAP, ac)) {
    return AUTOCOMPLETE_MAP[ac];
  }
  // input type=email/tel are strong signals too.
  const type = normalize(field.type);
  if (type === 'email') return 'email';
  if (type === 'tel') return 'phone';

  // 2-4. fuzzy over the remaining signals, most reliable first.
  const haystacks = [field.ariaLabel, field.label, field.name, field.id, field.placeholder]
    .map(normalizeForFuzzy)
    .filter(Boolean);

  for (const rule of KEYWORD_RULES) {
    for (const hay of haystacks) {
      if (rule.any.some((kw) => includesWord(hay, normalizeForFuzzy(kw)))) {
        return rule.key;
      }
    }
  }
  return null;
}

/**
 * Resolve the string value to type into a field for a given profile.
 * Falls back to composing fullName from first/last (and vice versa).
 */
function fillValueFor(field, profile) {
  const key = mapFieldToProfileKey(field);
  if (!key || !profile) return null;

  if (profile[key] != null && profile[key] !== '') return profile[key];

  if (key === 'fullName' && (profile.firstName || profile.lastName)) {
    return [profile.firstName, profile.lastName].filter(Boolean).join(' ');
  }
  if (key === 'firstName' && profile.fullName) {
    return profile.fullName.split(/\s+/)[0];
  }
  if (key === 'lastName' && profile.fullName) {
    const parts = profile.fullName.split(/\s+/);
    return parts.length > 1 ? parts[parts.length - 1] : null;
  }
  return null;
}

const api = { mapFieldToProfileKey, fillValueFor, PROFILE_KEYS };

// Work both as a CommonJS module (node --test) and a browser global.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.CareerAgentFieldMapping = api;
}
