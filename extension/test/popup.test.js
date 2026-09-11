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
