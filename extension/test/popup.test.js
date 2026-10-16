'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { parseImport, FIELDS } = require('../src/popup.js');

test('imports the profile JSON the CareerAgent app exports', () => {
  const profile = parseImport(
    JSON.stringify({
      fullName: 'Ada Lovelace',
      email: 'ada@example.com',
      phone: '+44 20 7946 0958',
      linkedin: 'https://linkedin.com/in/ada',
      github: 'https://github.com/ada',
      portfolio: '',
      location: '',
    })
  );
  assert.deepEqual(Object.keys(profile).sort(), [...FIELDS].sort());
  assert.equal(profile.fullName, 'Ada Lovelace');
  assert.equal(profile.github, 'https://github.com/ada');
});

test('only known fields survive the import', () => {
  const profile = parseImport(
    JSON.stringify({ email: 'ada@example.com', raw_text: 'whole CV', ssn: '123' })
  );
  assert.equal(profile.email, 'ada@example.com');
  assert.equal(profile.raw_text, undefined);
  assert.equal(profile.ssn, undefined);
});

test('missing and non-string values become empty strings, never undefined', () => {
  const profile = parseImport(JSON.stringify({ fullName: null, phone: 42 }));
  FIELDS.forEach((f) => assert.equal(typeof profile[f], 'string'));
  assert.equal(profile.fullName, '');
  assert.equal(profile.phone, '');
});

test('values are trimmed', () => {
  assert.equal(parseImport('{"email":"   ada@example.com   "}').email, 'ada@example.com');
});

test('rejects anything that is not a JSON object', () => {
  assert.throws(() => parseImport('not json'));
  assert.throws(() => parseImport('[1,2,3]'), /expected a JSON object/);
  assert.throws(() => parseImport('null'), /expected a JSON object/);
  assert.throws(() => parseImport('"a string"'), /expected a JSON object/);
});

// --- Candidate answers + resume (the facade.extension_profile contract) ---

const fs = require('node:fs');
const path = require('node:path');
const { withEdits, importSummary, fillSummary } = require('../src/popup.js');
const { answerFor } = require('../src/field_mapping.js');

// Written by core.facade.extension_profile; tests/test_apply.py asserts the
// Python side still produces exactly this document.
const FIXTURE = fs.readFileSync(path.join(__dirname, 'fixtures', 'candidate_profile.json'), 'utf8');

test('the app-exported candidate profile imports intact', () => {
  const exported = JSON.parse(FIXTURE);
  const profile = parseImport(FIXTURE);
  assert.deepEqual(profile.answers, exported.answers);
  assert.equal(profile.location, 'London, UK');
  assert.equal(profile.portfolio, 'https://ada.dev');
  // ...and the imported answers drive the question filler.
  assert.equal(answerFor({ label: 'Do you need visa sponsorship?' }, profile).value, false);
  assert.equal(answerFor({ label: 'Pronouns' }, profile).value, 'she/her');
});

test('answers are whitelisted by key and type', () => {
  const profile = parseImport(
    JSON.stringify({
      email: 'a@b.com',
      answers: {
        work_authorized: 'yes', // wrong type -> unknown
        requires_sponsorship: false,
        notice_period: '  2 weeks ',
        ssn: '123',
      },
    })
  );
  assert.deepEqual(profile.answers, { requires_sponsorship: false, notice_period: '2 weeks' });
});

test('demographics are dropped on import without the consent marker', () => {
  const noConsent = parseImport(JSON.stringify({ answers: { gender: 'Woman' } }));
  assert.equal(noConsent.answers, undefined);
  const consent = parseImport(
    JSON.stringify({ answers: { gender: 'Woman', share_demographics: true } })
  );
  assert.deepEqual(consent.answers, { gender: 'Woman', share_demographics: true });
});

test('a valid resume block is kept, a bad one silently dropped', () => {
  const data_b64 = Buffer.from('%PDF-1.4').toString('base64');
  const ok = parseImport(
    JSON.stringify({ resume: { filename: 'a.pdf', mime: 'application/pdf', data_b64 } })
  );
  assert.equal(ok.resume.filename, 'a.pdf');
  const bad = parseImport(JSON.stringify({ resume: { mime: 'text/html', data_b64 } }));
  assert.equal(bad.resume, undefined);
});

test('editing the visible fields keeps imported answers and resume', () => {
  const stored = parseImport(FIXTURE);
  stored.resume = { filename: 'a.pdf', mime: 'application/pdf', data_b64: 'JVBERg==' };
  const next = withEdits(stored, { fullName: 'Ada King', email: 'ada@example.com' });
  assert.equal(next.fullName, 'Ada King');
  assert.equal(next.phone, ''); // a cleared input clears the field
  assert.deepEqual(next.answers, stored.answers);
  assert.deepEqual(next.resume, stored.resume);
});

test('status lines say what happened and hand back to the human', () => {
  assert.match(importSummary(parseImport(FIXTURE)), /9 screening answer\(s\)/);
  const text = fillSummary({ filled: 5, answered: 2, attached: 1, needsYou: ['Gender'] });
  assert.match(text, /Filled 5 field\(s\), answered 2 question\(s\), attached your resume\./);
  assert.match(text, /1 question\(s\) need your answer/);
  assert.match(text, /submit yourself\.$/);
  assert.match(fillSummary(null), /Open the application page/);
});
