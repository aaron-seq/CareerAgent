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
  { key: 'portfolio', any: ['portfolio', 'website', 'personal site', 'url'] },
  { key: 'location', any: ['location', 'city', 'address'] },
  { key: 'fullName', any: ['full name', 'fullname', 'your name', 'name'] },
];

function normalize(text) {
  return (text || '').toString().trim().toLowerCase();
}

// For fuzzy matching, treat separators (_ -) as spaces so "given_name" and
// "given-name" match the "given name" keyword.
function normalizeForFuzzy(text) {
  return normalize(text).replace(/[_-]+/g, ' ');
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
      if (rule.any.some((kw) => hay.includes(kw))) {
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

// ---------------------------------------------------------------------------
// Application questions (work authorization, salary, availability)
//
// These are the questions that stall an autofill run: they are usually a
// <select> or a radio pair rather than a text input, and the wording varies.
// A rule matches on keywords and declares which answer key it needs; if the
// profile has no answer, we leave the question alone for the human.
// ---------------------------------------------------------------------------

const QUESTION_RULES = [
  {
    key: 'requires_sponsorship',
    type: 'boolean',
    // Check sponsorship BEFORE authorization: "will you require sponsorship"
    // also contains none of the auth keywords, but auth phrasing sometimes
    // contains "sponsor", so order matters.
    any: [
      'require sponsorship',
      'need sponsorship',
      'require visa sponsorship',
      'need visa sponsorship',
      'require immigration',
      'sponsorship for an employment visa',
      'sponsorship now or in the future',
    ],
  },
  {
    key: 'work_authorized',
    type: 'boolean',
    any: [
      'legally authorized to work',
      'authorized to work',
      'authorised to work',
      'legally eligible to work',
      'right to work',
      'work authorization',
      'work authorisation',
    ],
  },
  {
    key: 'willing_to_relocate',
    type: 'boolean',
    any: ['willing to relocate', 'open to relocation', 'able to relocate'],
  },
  {
    key: 'salary_expectation',
    type: 'text',
    any: [
      'salary expectation',
      'expected salary',
      'desired salary',
      'compensation expectation',
      'salary requirement',
    ],
  },
  {
    key: 'notice_period',
    type: 'text',
    any: ['notice period', 'how much notice'],
  },
  {
    key: 'start_date',
    type: 'text',
    any: ['start date', 'when can you start', 'earliest start', 'available to start'],
  },
  { key: 'visa_status', type: 'text', any: ['visa status', 'current visa'] },
  { key: 'pronouns', type: 'text', any: ['pronoun'] },
  {
    key: 'cover_note',
    type: 'text',
    any: ['why do you want', 'why are you interested', 'cover letter', 'tell us about'],
  },
];

/**
 * Identify which application question a field is asking, if any.
 * @returns {{key: string, type: string}|null}
 */
function mapFieldToQuestion(field) {
  if (!field) return null;
  const haystacks = [field.ariaLabel, field.label, field.name, field.id, field.placeholder]
    .map(normalizeForFuzzy)
    .filter(Boolean);
  for (const rule of QUESTION_RULES) {
    for (const hay of haystacks) {
      if (rule.any.some((kw) => hay.includes(kw))) {
        return { key: rule.key, type: rule.type };
      }
    }
  }
  return null;
}

/**
 * The answer to type/select for a question field, or null to leave it alone.
 *
 * Returning null for an unknown answer is the whole point: an unanswered
 * work-authorization question is far better than a wrong one.
 */
function answerFor(field, profile) {
  const question = mapFieldToQuestion(field);
  if (!question || !profile || !profile.answers) return null;
  const value = profile.answers[question.key];
  if (value === undefined || value === null || value === '') return null;
  if (question.type === 'boolean') {
    if (typeof value !== 'boolean') return null;
    return { type: 'boolean', value };
  }
  return { type: 'text', value: String(value) };
}

/** Pick the <option> that represents a yes/no answer. */
function matchOptionForBoolean(optionTexts, value) {
  const yes = ['yes', 'true', 'i am', 'i do'];
  const no = ['no', 'false', 'i am not', 'i do not', "i don't"];
  const wanted = value ? yes : no;
  const unwanted = value ? no : yes;
  for (let i = 0; i < optionTexts.length; i += 1) {
    const text = normalize(optionTexts[i]);
    if (!text) continue;
    // Require an exact-ish match so "No" doesn't match "Not sure".
    if (wanted.some((w) => text === w || text.startsWith(`${w},`) || text.startsWith(`${w} `))) {
      // Guard against the opposite answer also matching a prefix.
      if (!unwanted.some((u) => text === u)) return i;
    }
  }
  return -1;
}

const api = {
  mapFieldToProfileKey,
  fillValueFor,
  mapFieldToQuestion,
  answerFor,
  matchOptionForBoolean,
  PROFILE_KEYS,
  QUESTION_RULES,
};

// Work both as a CommonJS module (node --test) and a browser global.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.CareerAgentFieldMapping = api;
}
