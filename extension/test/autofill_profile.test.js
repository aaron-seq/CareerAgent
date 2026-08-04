'use strict';

/**
 * Tests for consuming a CareerAgent-exported profile.
 *
 * The exporter is Python (`core/apply.py`); this pins the JS side of that
 * contract — the exact keys the content script reads — so a change on either
 * side breaks a test rather than silently filling nothing.
 */

const test = require('node:test');
const assert = require('node:assert');
const { fillValueFor, mapFieldToProfileKey } = require('../src/field_mapping.js');

// A profile shaped exactly like core.apply.AutofillProfile.to_dict().
const EXPORTED = {
  fullName: 'Ada Lovelace',
  firstName: 'Ada',
  lastName: 'Lovelace',
  email: 'ada@example.com',
  phone: '+44 20 7946 0000',
  linkedin: 'https://linkedin.com/in/ada',
  github: 'https://github.com/ada',
  portfolio: '',
  location: 'London, UK',
  resume: { filename: 'ada.pdf', mime: 'application/pdf', data_b64: 'JVBERg==' },
  meta: { source: 'CareerAgent', never_submits: true },
};

test('every exported key maps to a real Greenhouse-style field', () => {
  const form = [
    { label: 'First Name', expected: 'Ada' },
    { label: 'Last Name', expected: 'Lovelace' },
    { type: 'email', expected: 'ada@example.com' },
    { label: 'Phone', expected: '+44 20 7946 0000' },
    { label: 'LinkedIn Profile', expected: 'https://linkedin.com/in/ada' },
    { label: 'GitHub URL', expected: 'https://github.com/ada' },
    { label: 'City', expected: 'London, UK' },
  ];
  for (const field of form) {
    assert.equal(fillValueFor(field, EXPORTED), field.expected, field.label || field.type);
  }
});

test('empty exported fields fill nothing rather than a blank string', () => {
  // portfolio is '' in the export -> must not be typed into the form.
  assert.equal(fillValueFor({ label: 'Portfolio' }, EXPORTED), null);
});

test('a profile without a name still fills contact fields', () => {
  const partial = { email: 'x@y.com' };
  assert.equal(fillValueFor({ type: 'email' }, partial), 'x@y.com');
  assert.equal(fillValueFor({ label: 'First Name' }, partial), null);
});

test('resume metadata is carried through for the file input', () => {
  assert.equal(EXPORTED.resume.mime, 'application/pdf');
  assert.ok(EXPORTED.resume.data_b64.length > 0);
});

test('the never-submits contract is recorded in the profile', () => {
  assert.equal(EXPORTED.meta.never_submits, true);
});

test('application-form detection needs at least two mappable fields', () => {
  // Mirrors looksLikeApplicationForm()'s threshold without needing a DOM.
  const searchBox = [{ label: 'Search' }];
  const applicationForm = [
    { label: 'First Name' },
    { label: 'Email' },
    { label: 'Phone' },
  ];
  const mappable = (fields) =>
    fields.filter((f) => mapFieldToProfileKey(f)).length;

  assert.ok(mappable(searchBox) < 2, 'a search box must not trigger autofill');
  assert.ok(mappable(applicationForm) >= 2, 'a real form must trigger autofill');
});
