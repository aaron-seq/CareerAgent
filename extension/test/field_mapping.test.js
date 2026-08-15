'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { mapFieldToProfileKey, fillValueFor } = require('../src/field_mapping.js');

test('autocomplete tokens map to profile keys', () => {
  assert.equal(mapFieldToProfileKey({ autocomplete: 'given-name' }), 'firstName');
  assert.equal(mapFieldToProfileKey({ autocomplete: 'family-name' }), 'lastName');
  assert.equal(mapFieldToProfileKey({ autocomplete: 'email' }), 'email');
  assert.equal(mapFieldToProfileKey({ autocomplete: 'tel' }), 'phone');
});

test('input type is a strong signal', () => {
  assert.equal(mapFieldToProfileKey({ type: 'email' }), 'email');
  assert.equal(mapFieldToProfileKey({ type: 'tel' }), 'phone');
});

test('label / aria-label fuzzy matching', () => {
  assert.equal(mapFieldToProfileKey({ label: 'First Name' }), 'firstName');
  assert.equal(mapFieldToProfileKey({ ariaLabel: 'Last name' }), 'lastName');
  assert.equal(mapFieldToProfileKey({ label: 'LinkedIn Profile URL' }), 'linkedin');
  assert.equal(mapFieldToProfileKey({ label: 'GitHub' }), 'github');
});

test('name/id fuzzy matching with varied conventions', () => {
  assert.equal(mapFieldToProfileKey({ name: 'given_name' }), 'firstName');
  assert.equal(mapFieldToProfileKey({ id: 'firstname' }), 'firstName');
  assert.equal(mapFieldToProfileKey({ name: 'candidate_email' }), 'email');
});

test('specific rules beat generic name rule', () => {
  // "First Name" must map to firstName, not fullName (which also matches "name")
  assert.equal(mapFieldToProfileKey({ label: 'First Name' }), 'firstName');
  assert.equal(mapFieldToProfileKey({ label: 'Full Name' }), 'fullName');
});

test('placeholder is the lowest-priority signal', () => {
  assert.equal(mapFieldToProfileKey({ placeholder: 'you@example.com' }), null);
  assert.equal(mapFieldToProfileKey({ placeholder: 'Enter your email' }), 'email');
});

test('unknown fields return null', () => {
  assert.equal(mapFieldToProfileKey({ label: 'Favorite color' }), null);
  assert.equal(mapFieldToProfileKey(null), null);
});

test('a bare "URL" suffix does not steal unrelated service fields', () => {
  // Seen on a real live Lever form: "Twitter URL" was wrongly mapped to
  // "portfolio" because the portfolio rule used to match on "url" alone.
  // There's no profile key for Twitter, so it should now map to nothing.
  assert.equal(mapFieldToProfileKey({ label: 'Twitter URL' }), null);
  // Fields that are actually about the portfolio/website still match.
  assert.equal(mapFieldToProfileKey({ label: 'Portfolio URL' }), 'portfolio');
  assert.equal(mapFieldToProfileKey({ label: 'Personal Website' }), 'portfolio');
});

test('short keywords do not false-positive inside unrelated words', () => {
  // Seen on a real live Greenhouse posting: a custom question labeled
  // "...complete the Constellation application form" was wrongly mapped to
  // "phone" because "tel" is a substring of "Constellation".
  assert.equal(
    mapFieldToProfileKey({ label: 'Please complete the Constellation application form' }),
    null
  );
  // But real phone labels/abbreviations still match, including a trailing
  // colon (a very common label convention this fix must not break).
  assert.equal(mapFieldToProfileKey({ label: 'Tel:' }), 'phone');
  assert.equal(mapFieldToProfileKey({ label: 'Home tel number' }), 'phone');
  assert.equal(mapFieldToProfileKey({ label: 'Telephone' }), 'phone');
});

test('fillValueFor resolves values from the profile', () => {
  const profile = { email: 'a@b.com', firstName: 'Ada', lastName: 'Lovelace' };
  assert.equal(fillValueFor({ autocomplete: 'email' }, profile), 'a@b.com');
  assert.equal(fillValueFor({ label: 'First Name' }, profile), 'Ada');
});

test('fillValueFor composes fullName from parts', () => {
  const profile = { firstName: 'Ada', lastName: 'Lovelace' };
  assert.equal(fillValueFor({ autocomplete: 'name' }, profile), 'Ada Lovelace');
});

test('fillValueFor splits fullName into first/last', () => {
  const profile = { fullName: 'Ada Lovelace' };
  assert.equal(fillValueFor({ label: 'First Name' }, profile), 'Ada');
  assert.equal(fillValueFor({ label: 'Last Name' }, profile), 'Lovelace');
});

test('fillValueFor returns null when nothing matches', () => {
  assert.equal(fillValueFor({ label: 'Favorite color' }, { email: 'a@b.com' }), null);
});
