'use strict';

/**
 * Screening questions: work authorization, sponsorship, salary, EEO.
 *
 * The critical property: an *unknown* answer yields null -- the question is
 * left for the human -- never a guessed "No" on a real application.
 */

const test = require('node:test');
const assert = require('node:assert');
const {
  mapFieldToQuestion,
  answerFor,
  classifyField,
  matchOptionForBoolean,
  matchOptionForText,
  CONSENT_KEY,
} = require('../src/field_mapping.js');

const PROFILE = {
  email: 'ada@example.com',
  location: 'London, UK',
  answers: {
    work_authorization_country: 'US',
    work_authorized: true,
    requires_sponsorship: false,
    salary_expectation: 'GBP 90,000 per year',
    notice_period: '4 weeks',
    willing_to_relocate: false,
    gender: 'Woman',
  },
};

test('recognises the standard work-authorization phrasings', () => {
  for (const label of [
    'Are you legally authorized to work in the United States?',
    'Are you authorised to work in the UK?',
    'Do you have the right to work in Ireland?',
    'Work Authorization',
  ]) {
    assert.equal(mapFieldToQuestion({ label }).key, 'work_authorized', label);
  }
});

test('sponsorship is distinguished from authorization', () => {
  for (const label of [
    'Will you now or in the future require sponsorship for an employment visa?',
    'Do you need visa sponsorship?',
    'Will you require sponsorship to remain authorized to work?',
  ]) {
    assert.equal(mapFieldToQuestion({ label }).key, 'requires_sponsorship', label);
  }
});

test('maps salary, notice, start date, relocation and EEO questions', () => {
  assert.equal(mapFieldToQuestion({ label: 'Salary Expectations' }).key, 'salary_expectation');
  assert.equal(mapFieldToQuestion({ label: 'Notice period' }).key, 'notice_period');
  assert.equal(mapFieldToQuestion({ label: 'When can you start?' }).key, 'start_date');
  assert.equal(
    mapFieldToQuestion({ label: 'Are you willing to relocate?' }).key,
    'willing_to_relocate'
  );
  assert.equal(mapFieldToQuestion({ label: 'Gender' }).key, 'gender');
  assert.equal(mapFieldToQuestion({ label: 'Veteran Status' }).key, 'veteran_status');
  assert.equal(mapFieldToQuestion({ name: 'disability_status' }).key, 'disability_status');
});

test('identity fields and short-word lookalikes are not questions', () => {
  assert.equal(mapFieldToQuestion({ label: 'First Name' }), null);
  assert.equal(mapFieldToQuestion({ label: 'Search jobs' }), null);
  assert.equal(mapFieldToQuestion({ label: 'Tracing experience' }), null); // "race"
  assert.equal(mapFieldToQuestion(null), null);
});

test('answerFor returns typed answers from the profile', () => {
  assert.deepEqual(answerFor({ label: 'Are you authorized to work in the US?' }, PROFILE), {
    key: 'work_authorized',
    type: 'boolean',
    value: true,
  });
  assert.deepEqual(answerFor({ label: 'Will you require sponsorship in the United States?' }, PROFILE), {
    key: 'requires_sponsorship',
    type: 'boolean',
    value: false,
  });
  assert.equal(answerFor({ label: 'Salary expectation' }, PROFILE).value, 'GBP 90,000 per year');
});

test('an unknown answer is left for the human, not guessed', () => {
  const empty = { email: 'a@b.com', answers: {} };
  assert.equal(answerFor({ label: 'Are you authorized to work in the US?' }, empty), null);
  assert.equal(answerFor({ label: 'Are you authorized to work?' }, { email: 'x' }), null);
  // A wrongly-typed answer is treated as unknown too.
  const wrong = { answers: { work_authorized: 'yes' } };
  assert.equal(answerFor({ label: 'Are you authorized to work?' }, wrong), null);
});

test('demographic answers need the explicit consent marker', () => {
  assert.equal(answerFor({ label: 'Gender' }, PROFILE), null);
  const consented = { answers: { ...PROFILE.answers, [CONSENT_KEY]: true } };
  assert.equal(answerFor({ label: 'Gender' }, consented).value, 'Woman');
});

test('questions win over identity fields; unknowns are classified, not filled', () => {
  const field = { label: 'Are you authorized to work in this location?' };
  const decision = classifyField(field, { location: 'London', answers: {} });
  assert.equal(decision.kind, 'question');
  assert.equal(decision.key, 'work_authorized');
  assert.equal(decision.answer, null);

  assert.deepEqual(classifyField({ label: 'City' }, PROFILE), {
    kind: 'profile',
    key: 'location',
    value: 'London, UK',
  });
  assert.equal(classifyField({ label: 'Favourite colour' }, PROFILE), null);
});

test('boolean option matching picks the right dropdown entry', () => {
  assert.equal(matchOptionForBoolean(['Please select', 'Yes', 'No'], true), 1);
  assert.equal(matchOptionForBoolean(['Please select', 'Yes', 'No'], false), 2);
});

test('boolean matching does not confuse "No" with "Not sure"', () => {
  assert.equal(matchOptionForBoolean(['Not sure', 'No', 'Yes'], false), 1);
});

test('boolean matching reads sentence-style options, negatives first', () => {
  const options = ['I am authorized', 'I am not authorized'];
  assert.equal(matchOptionForBoolean(options, true), 0);
  assert.equal(matchOptionForBoolean(options, false), 1);
  const sponsor = ['Yes, I will require sponsorship', "No, I don't require sponsorship"];
  assert.equal(matchOptionForBoolean(sponsor, true), 0);
  assert.equal(matchOptionForBoolean(sponsor, false), 1);
});

test('no match means -1, so the question is flagged instead', () => {
  assert.equal(matchOptionForBoolean(['Maybe', 'Unclear'], true), -1);
  assert.equal(matchOptionForBoolean([], false), -1);
});

test('text option matching is exact, so "Male" never selects "Female"', () => {
  const options = ['Select...', 'Female', 'Male', 'Decline to self-identify'];
  assert.equal(matchOptionForText(options, 'Male'), 2);
  assert.equal(matchOptionForText(options, 'Woman'), -1);
  assert.equal(matchOptionForText(['She/Her', 'He/Him'], 'she/her'), 0);
  assert.equal(matchOptionForText(options, ''), -1);
});


test('eligibility answers require the explicitly matching country', () => {
  const uk = { answers: { work_authorization_country: 'United Kingdom', work_authorized: true, requires_sponsorship: false, visa_status: 'British citizen' } };
  for (const country of ['UK', 'GB', 'United Kingdom', 'U.K.']) {
    assert.equal(answerFor({ label: `Are you authorized to work in the ${country}?` }, uk).value, true);
    assert.equal(answerFor({ label: `Do you need visa sponsorship in the ${country}?` }, uk).value, false);
  }
  for (const label of [
    'Are you authorized to work in the United States?',
    'Are you authorized to work in Canada?',
    'Are you authorized to work in Atlantis?',
    'Are you authorized to work in this country?',
    'Are you authorized to work?',
    'Will you require sponsorship?',
    'Will you require sponsorship in the US?',
    'Current visa status in India?',
    'Visa status',
  ]) assert.equal(answerFor({ label }, uk), null, label);
  assert.equal(answerFor({ label: 'Current visa status in the UK?' }, uk).value, 'British citizen');
  const noCountry = { answers: { work_authorized: true, requires_sponsorship: false } };
  assert.equal(answerFor({ label: 'Are you authorized to work in the UK?' }, noCountry), null);
  const unknownCountry = { answers: { ...uk.answers, work_authorization_country: 'Atlantis' } };
  assert.equal(answerFor({ label: 'Are you authorized to work in Atlantis?' }, unknownCountry), null);
});

test('negated and compound questions are recognized but left for the human', () => {
  for (const label of [
    'Are you not authorized to work in the United States?',
    'Do you not require sponsorship in the United States?',
    'Are you authorized to work in the United States without visa sponsorship?',
    'Are you authorized to work without visa sponsorship?',
    'Are you authorized to work in the US and do you require sponsorship?',
    'Will you require sponsorship to remain authorized to work in the US?',
    'Are you willing to relocate without assistance?',
  ]) {
    assert.ok(mapFieldToQuestion({ label }), label);
    assert.equal(answerFor({ label }, PROFILE), null, label);
  }
  assert.equal(answerFor({ label: 'Do you not require sponsorship in the US?', name: 'work_authorized' }, PROFILE), null);
});
