'use strict';

/**
 * Application-question handling: work authorization, sponsorship, salary.
 *
 * These are the fields that stall a run. The critical property under test is
 * that an *unknown* answer produces null — leaving the question for the human
 * — rather than a guessed "No" on a real application.
 */

const test = require('node:test');
const assert = require('node:assert');
const {
  mapFieldToQuestion,
  answerFor,
  matchOptionForBoolean,
} = require('../src/field_mapping.js');

const PROFILE = {
  email: 'ada@example.com',
  answers: {
    work_authorized: true,
    requires_sponsorship: false,
    salary_expectation: 'GBP 90,000 per year',
    notice_period: '4 weeks',
    willing_to_relocate: false,
  },
};

test('recognises the standard work-authorization phrasings', () => {
  const phrasings = [
    'Are you legally authorized to work in the United States?',
    'Are you authorised to work in the UK?',
    'Do you have the right to work in Ireland?',
    'Work Authorization',
  ];
  for (const label of phrasings) {
    assert.equal(mapFieldToQuestion({ label }).key, 'work_authorized', label);
  }
});

test('sponsorship is distinguished from authorization', () => {
  const sponsorship = [
    'Will you now or in the future require sponsorship for an employment visa?',
    'Do you need visa sponsorship?',
    'Will you require sponsorship?',
  ];
  for (const label of sponsorship) {
    assert.equal(mapFieldToQuestion({ label }).key, 'requires_sponsorship', label);
  }
});

test('maps salary, notice, start date and relocation', () => {
  assert.equal(mapFieldToQuestion({ label: 'Salary Expectations' }).key, 'salary_expectation');
  assert.equal(mapFieldToQuestion({ label: 'Notice period' }).key, 'notice_period');
  assert.equal(mapFieldToQuestion({ label: 'When can you start?' }).key, 'start_date');
  assert.equal(mapFieldToQuestion({ label: 'Are you willing to relocate?' }).key, 'willing_to_relocate');
});

test('unrelated fields are not treated as questions', () => {
  assert.equal(mapFieldToQuestion({ label: 'First Name' }), null);
  assert.equal(mapFieldToQuestion({ label: 'Search jobs' }), null);
  assert.equal(mapFieldToQuestion(null), null);
});

test('answerFor returns typed answers from the profile', () => {
  const auth = answerFor({ label: 'Are you authorized to work in the US?' }, PROFILE);
  assert.deepEqual(auth, { type: 'boolean', value: true });

  const sponsor = answerFor({ label: 'Will you require sponsorship?' }, PROFILE);
  assert.deepEqual(sponsor, { type: 'boolean', value: false });

  const salary = answerFor({ label: 'Salary expectation' }, PROFILE);
  assert.deepEqual(salary, { type: 'text', value: 'GBP 90,000 per year' });
});

test('an unknown answer is left for the human, not guessed', () => {
  const empty = { email: 'a@b.com', answers: {} };
  assert.equal(answerFor({ label: 'Are you authorized to work in the US?' }, empty), null);
  // A profile with no answers block at all must also be safe.
  assert.equal(answerFor({ label: 'Are you authorized to work?' }, { email: 'x' }), null);
});

test('boolean option matching picks the right dropdown entry', () => {
  const options = ['Please select', 'Yes', 'No'];
  assert.equal(matchOptionForBoolean(options, true), 1);
  assert.equal(matchOptionForBoolean(options, false), 2);
});

test('boolean matching does not confuse "No" with "Not sure"', () => {
  const options = ['Not sure', 'No', 'Yes'];
  assert.equal(matchOptionForBoolean(options, false), 1, 'must pick "No", not "Not sure"');
});

test('boolean matching handles sentence-style options', () => {
  const options = ['Yes, I am authorized', 'No, I require sponsorship'];
  assert.equal(matchOptionForBoolean(options, true), 0);
  assert.equal(matchOptionForBoolean(options, false), 1);
});

test('boolean matching returns -1 when nothing matches', () => {
  assert.equal(matchOptionForBoolean(['Maybe', 'Unclear'], true), -1);
});
