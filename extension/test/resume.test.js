'use strict';

const test = require('node:test');
const assert = require('node:assert');
const {
  isResumeField,
  validateResume,
  decodeResume,
  MAX_RESUME_B64,
} = require('../src/field_mapping.js');

const PDF_B64 = Buffer.from('%PDF-1.4 tiny').toString('base64');
const RESUME = { filename: 'Ada_Lovelace.pdf', mime: 'application/pdf', data_b64: PDF_B64 };

test('recognises resume uploads on the supported ATS forms', () => {
  assert.ok(isResumeField({ id: 'resume', type: 'file' })); // Greenhouse
  assert.ok(isResumeField({ name: 'resume' })); // Lever
  assert.ok(isResumeField({ id: '_systemfield_resume' })); // Ashby
  assert.ok(isResumeField({ label: 'Résumé/CV' }));
});

test('never treats a cover-letter or other upload as the resume', () => {
  assert.equal(isResumeField({ id: 'cover_letter', label: 'Cover Letter' }), false);
  assert.equal(isResumeField({ label: 'Upload your cover letter or resume' }), false);
  assert.equal(isResumeField({ label: 'Transcript' }), false);
  assert.equal(isResumeField(null), false);
});

test('validateResume accepts the exported PDF block', () => {
  assert.deepEqual(validateResume(RESUME), RESUME);
});

test('validateResume rejects anything that is not a bounded base64 PDF', () => {
  assert.equal(validateResume(null), null);
  assert.equal(validateResume({ ...RESUME, mime: 'text/html' }), null);
  assert.equal(validateResume({ ...RESUME, data_b64: 'not base64!' }), null);
  assert.equal(
    validateResume({ ...RESUME, data_b64: Buffer.from('<html>').toString('base64') }),
    null
  );
  assert.equal(validateResume({ ...RESUME, data_b64: 'J'.repeat(MAX_RESUME_B64 + 4) }), null);
});

test('validateResume sanitises the filename', () => {
  assert.equal(validateResume({ ...RESUME, filename: '../../etc/passwd' }).filename, 'resume.pdf');
  assert.equal(validateResume({ ...RESUME, filename: 'a b<c>.pdf' }).filename, 'abc.pdf');
});

test('decodeResume yields the original bytes', () => {
  const decoded = decodeResume(RESUME);
  assert.equal(Buffer.from(decoded.bytes).toString(), '%PDF-1.4 tiny');
  assert.equal(decoded.mime, 'application/pdf');
  assert.equal(decodeResume({ mime: 'application/pdf' }), null);
});

test('undecodable base64 is rejected up front, never thrown mid-fill', () => {
  // Codex review on #51: 'JVBER' passes the alphabet and %PDF-prefix checks,
  // but its length isn't a multiple of 4, so atob() threw inside the fill
  // request instead of the bad import being dropped.
  for (const data of ['JVBER', 'JVBERi0', 'JVBERi0xLjQ=x', 'JVBER===']) {
    const resume = { ...RESUME, data_b64: data };
    assert.equal(validateResume(resume), null, data);
    assert.doesNotThrow(() => decodeResume(resume), data);
    assert.equal(decodeResume(resume), null, data);
  }
});
