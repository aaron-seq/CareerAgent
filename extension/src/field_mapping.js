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
  // Strip diacritics so "Résumé" matches "resume".
  return (text || '')
    .toString()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
    .toLowerCase();
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

// ---------------------------------------------------------------------------
// Screening questions (work authorization, sponsorship, salary, start date...)
//
// These usually arrive as a <select> or a yes/no radio group, and they are
// what stalls an autofill run. Answers come from `profile.answers`, which the
// app builds from the candidate's own CandidateProfile (core/apply.py
// build_answers). The keys below are that contract; tests/test_apply.py
// checks every Python key appears here.
//
// Rule: an absent answer is UNKNOWN. The question is left blank and flagged
// for the human -- never answered with a guessed "No".
// ---------------------------------------------------------------------------

const BOOLEAN_ANSWER_KEYS = ['work_authorized', 'requires_sponsorship', 'willing_to_relocate'];
const TEXT_ANSWER_KEYS = [
  'visa_status',
  'salary_expectation',
  'notice_period',
  'start_date',
  'cover_note',
];
// EEO answers: used only when the export carries the consent marker.
const DEMOGRAPHIC_ANSWER_KEYS = [
  'pronouns',
  'gender',
  'ethnicity',
  'veteran_status',
  'disability_status',
];
const CONSENT_KEY = 'share_demographics';

// Ordered: sponsorship is checked before authorization because sponsorship
// questions often also say "authorized", never the reverse.
const QUESTION_RULES = [
  {
    key: 'requires_sponsorship',
    type: 'boolean',
    any: [
      'require sponsorship',
      'need sponsorship',
      'visa sponsorship',
      'immigration sponsorship',
      'sponsorship for an employment visa',
      'sponsorship now or in the future',
      'require immigration',
    ],
  },
  {
    key: 'work_authorized',
    type: 'boolean',
    any: [
      'authorized to work',
      'authorised to work',
      'eligible to work',
      'right to work',
      'work authorization',
      'work authorisation',
    ],
  },
  {
    key: 'willing_to_relocate',
    type: 'boolean',
    any: ['willing to relocate', 'open to relocation', 'able to relocate', 'open to relocating'],
  },
  {
    key: 'salary_expectation',
    type: 'text',
    any: [
      'salary expectation',
      'salary expectations',
      'expected salary',
      'desired salary',
      'salary requirement',
      'salary requirements',
      'compensation expectation',
      'compensation expectations',
      'expected compensation',
      'desired compensation',
    ],
  },
  { key: 'notice_period', type: 'text', any: ['notice period', 'how much notice'] },
  {
    key: 'start_date',
    type: 'text',
    any: ['start date', 'when can you start', 'earliest start', 'available to start'],
  },
  { key: 'visa_status', type: 'text', any: ['visa status', 'current visa', 'immigration status'] },
  {
    key: 'cover_note',
    type: 'text',
    any: ['why do you want', 'why are you interested', 'cover letter'],
  },
  { key: 'pronouns', type: 'text', any: ['pronoun', 'pronouns'] },
  { key: 'gender', type: 'text', any: ['gender', 'gender identity'] },
  { key: 'ethnicity', type: 'text', any: ['ethnicity', 'ethnic', 'race', 'racial'] },
  { key: 'veteran_status', type: 'text', any: ['veteran', 'veterans'] },
  { key: 'disability_status', type: 'text', any: ['disability', 'disabled'] },
];

function haystacksFor(field) {
  return [field.ariaLabel, field.label, field.name, field.id, field.placeholder]
    .map(normalizeForFuzzy)
    .filter(Boolean);
}

/**
 * Which screening question a field asks, if any.
 * @returns {{key: string, type: string}|null}
 */
function mapFieldToQuestion(field) {
  if (!field) return null;
  const haystacks = haystacksFor(field);
  for (const rule of QUESTION_RULES) {
    for (const hay of haystacks) {
      if (rule.any.some((kw) => includesWord(hay, normalizeForFuzzy(kw)))) {
        return { key: rule.key, type: rule.type };
      }
    }
  }
  return null;
}

/**
 * The candidate's answer to a question field, or null to leave it blank.
 * @returns {{key: string, type: 'boolean'|'text', value: boolean|string}|null}
 */
function answerFor(field, profile) {
  const question = mapFieldToQuestion(field);
  if (!question || !profile || !profile.answers) return null;
  const answers = profile.answers;
  if (DEMOGRAPHIC_ANSWER_KEYS.includes(question.key) && answers[CONSENT_KEY] !== true) {
    return null;
  }
  const value = answers[question.key];
  if (question.type === 'boolean') {
    return typeof value === 'boolean' ? { key: question.key, type: 'boolean', value } : null;
  }
  if (typeof value !== 'string' || value.trim() === '') return null;
  return { key: question.key, type: 'text', value };
}

/**
 * Decide what a field is: a screening question (answered or not) or an
 * identity field. Questions win, so "Are you authorized to work in this
 * location?" is never filled with the candidate's city.
 * @returns {{kind: 'question', key: string, answer: object|null}|
 *           {kind: 'profile', key: string, value: string|null}|null}
 */
function classifyField(field, profile) {
  const question = mapFieldToQuestion(field);
  if (question) {
    return { kind: 'question', key: question.key, answer: answerFor(field, profile) };
  }
  const key = mapFieldToProfileKey(field);
  if (!key) return null;
  return { kind: 'profile', key, value: fillValueFor(field, profile) };
}

const NO_PREFIXES = ['no', 'false', 'i am not', 'i do not', 'i don t', 'i will not', 'i won t'];
const YES_PREFIXES = ['yes', 'true', 'i am', 'i do', 'i will'];

function startsWithPhrase(text, phrase) {
  return text === phrase || text.startsWith(phrase + ' ');
}

/** 'yes' | 'no' | null for one option's text. Negatives are checked first. */
function optionPolarity(text) {
  const t = normalizeForFuzzy(text);
  if (!t) return null;
  if (NO_PREFIXES.some((p) => startsWithPhrase(t, p))) return 'no';
  if (YES_PREFIXES.some((p) => startsWithPhrase(t, p))) return 'yes';
  return null;
}

/** Index of the option meaning yes/no, or -1 (then the human answers). */
function matchOptionForBoolean(optionTexts, value) {
  const wanted = value ? 'yes' : 'no';
  return optionTexts.findIndex((text) => optionPolarity(text) === wanted);
}

/** Index of the option equal to a text answer (exact, normalized), or -1. */
function matchOptionForText(optionTexts, value) {
  const wanted = normalizeForFuzzy(value);
  if (!wanted) return -1;
  return optionTexts.findIndex((text) => normalizeForFuzzy(text) === wanted);
}

// ---------------------------------------------------------------------------
// Resume attachment
// ---------------------------------------------------------------------------

// 2 MB of PDF as base64 (mirrors core/apply.py MAX_RESUME_BYTES).
const MAX_RESUME_B64 = Math.ceil((2 * 1024 * 1024) / 3) * 4;

/** Is this file input the resume upload (not a cover letter / transcript)? */
function isResumeField(field) {
  if (!field) return false;
  const haystacks = haystacksFor(field);
  if (haystacks.some((h) => includesWord(h, 'cover letter'))) return false;
  return haystacks.some((h) =>
    ['resume', 'cv', 'curriculum vitae'].some((kw) => includesWord(h, kw))
  );
}

/**
 * Validate an exported `resume` block. Returns a clean copy or null; never
 * throws, so a bad import can't break the popup or the page.
 */
function validateResume(resume) {
  if (!resume || typeof resume !== 'object' || Array.isArray(resume)) return null;
  const { filename, mime, data_b64: data } = resume;
  if (mime !== 'application/pdf') return null;
  if (typeof data !== 'string' || data.length === 0 || data.length > MAX_RESUME_B64) return null;
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(data)) return null;
  if (!data.startsWith('JVBER')) return null; // base64 of "%PDF"
  const name = typeof filename === 'string' ? filename.replace(/[^\w.-]/g, '') : '';
  return {
    filename: /\.pdf$/i.test(name) ? name : 'resume.pdf',
    mime,
    data_b64: data,
  };
}

/** Decode a validated resume to bytes for a File, or null. */
function decodeResume(resume) {
  const clean = validateResume(resume);
  if (!clean) return null;
  const binary = atob(clean.data_b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return { filename: clean.filename, mime: clean.mime, bytes };
}

const api = {
  mapFieldToProfileKey,
  fillValueFor,
  mapFieldToQuestion,
  answerFor,
  classifyField,
  matchOptionForBoolean,
  matchOptionForText,
  isResumeField,
  validateResume,
  decodeResume,
  PROFILE_KEYS,
  QUESTION_RULES,
  BOOLEAN_ANSWER_KEYS,
  TEXT_ANSWER_KEYS,
  DEMOGRAPHIC_ANSWER_KEYS,
  CONSENT_KEY,
  MAX_RESUME_B64,
};

// Work both as a CommonJS module (node --test) and a browser global.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.CareerAgentFieldMapping = api;
}
