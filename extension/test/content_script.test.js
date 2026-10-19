'use strict';

/**
 * Drives the real content script against a tiny fake DOM (node --test has no
 * browser). Pins the human-in-the-loop behaviour: known answers are filled,
 * unknown questions are left blank and flagged, filled values are never
 * clobbered, only the resume input gets the resume, and nothing submits.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = path.join(__dirname, '..', 'src');
const read = (f) => fs.readFileSync(path.join(SRC, f), 'utf8');

class FakeEl {
  constructor(tag, attrs = {}, extra = {}) {
    this.tagName = tag.toUpperCase();
    this.attrs = attrs;
    this.id = attrs.id || '';
    this.value = '';
    this.disabled = false;
    this.readOnly = false;
    this.style = {};
    this.events = [];
    this.labels = extra.label ? [{ textContent: extra.label }] : [];
    this.fieldset = extra.fieldset || null;
    this.parentElement = extra.parent || null;
    Object.assign(this, extra.props || {});
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }
  dispatchEvent(event) {
    this.events.push(event.type);
    return true;
  }
  getClientRects() {
    return [{ width: 200, height: 24 }]; // normal controls have real layout boxes
  }
  closest(selector) {
    return selector === 'fieldset' ? this.fieldset : null;
  }
  click() {
    this.checked = true;
    this.events.push('click');
  }
}

function fieldset(legend) {
  return { style: {}, querySelector: () => ({ textContent: legend }) };
}

function matches(el, selector) {
  if (selector === 'textarea') return el.tagName === 'TEXTAREA';
  if (selector === 'select') return el.tagName === 'SELECT';
  if (selector === 'input:not([type])') return el.tagName === 'INPUT' && !('type' in el.attrs);
  const m = /^input\[type=(\w+)\]$/.exec(selector);
  return Boolean(m) && el.tagName === 'INPUT' && el.attrs.type === m[1];
}

function load(elements) {
  let listener = null;
  const ctx = {
    Event: class {
      constructor(type) {
        this.type = type;
      }
    },
    File: class {
      constructor(parts, name, opts) {
        Object.assign(this, { parts, name, type: opts.type });
      }
    },
    DataTransfer: class {
      constructor() {
        this.files = [];
        this.items = { add: (f) => this.files.push(f) };
      }
    },
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    getComputedStyle: (el) => ({ display: 'block', visibility: 'visible', opacity: '1', ...el.style }),
    setTimeout: () => 0, // skip the delayed re-pass
    document: {
      querySelectorAll: (sel) =>
        elements.filter((el) => sel.split(',').some((s) => matches(el, s.trim()))),
      getElementById: () => null,
    },
    chrome: { runtime: { onMessage: { addListener: (fn) => (listener = fn) } } },
  };
  vm.createContext(ctx);
  vm.runInContext(read('field_mapping.js'), ctx);
  vm.runInContext(read('content_script.js'), ctx);
  return (profile) => {
    let response;
    listener({ type: 'CAREERAGENT_FILL', profile }, null, (r) => (response = r));
    return response;
  };
}

const PROFILE = {
  fullName: 'Ada Lovelace',
  email: 'ada@example.com',
  location: 'London, UK',
  answers: {
    work_authorization_country: 'United Kingdom',
    work_authorized: true,
    requires_sponsorship: false,
    cover_note: 'I build reliable data systems.',
    salary_expectation: 'GBP 90,000 per year',
  },
  resume: {
    filename: 'Ada.pdf',
    mime: 'application/pdf',
    data_b64: Buffer.from('%PDF-1.4').toString('base64'),
  },
};

function form() {
  const sponsor = fieldset('Will you now or in the future require visa sponsorship in the UK?');
  const relocate = fieldset('Are you willing to relocate?');
  const radio = (name, value, fs) =>
    new FakeEl('input', { type: 'radio', name, value }, { label: value, fieldset: fs, props: { checked: false } });
  const options = (...texts) => texts.map((t) => ({ textContent: t, value: t }));
  return {
    first: new FakeEl('input', { type: 'text', id: 'first_name' }, { label: 'First Name' }),
    email: new FakeEl('input', { type: 'email', id: 'email' }),
    city: new FakeEl('input', { type: 'text' }, { label: 'City' }),
    salary: new FakeEl('input', { type: 'text' }, { label: 'Salary expectations', props: { value: '100k' } }),
    why: new FakeEl('textarea', { id: 'q1' }, { label: 'Why do you want to work here?' }),
    auth: new FakeEl('select', { id: 'q2' }, {
      label: 'Are you legally authorized to work in the United Kingdom?',
      props: { options: options('Select...', 'Yes', 'No'), selectedIndex: 0 },
    }),
    gender: new FakeEl('select', { id: 'gender' }, {
      label: 'Gender',
      props: { options: options('Select...', 'Female', 'Male'), selectedIndex: 0 },
    }),
    sponsorYes: radio('sponsor', 'Yes', sponsor),
    sponsorNo: radio('sponsor', 'No', sponsor),
    relocateYes: radio('relocate', 'Yes', relocate),
    relocateNo: radio('relocate', 'No', relocate),
    relocateFieldset: relocate,
    resume: new FakeEl('input', { type: 'file', id: 'resume' }, { props: { files: [] } }),
    cover: new FakeEl('input', { type: 'file', id: 'cover_letter' }, { label: 'Cover Letter', props: { files: [] } }),
  };
}

function elementsOf(f) {
  return Object.values(f).filter((v) => v instanceof FakeEl);
}

test('fills identity fields and the questions the candidate answered', () => {
  const f = form();
  const res = load(elementsOf(f))(PROFILE);
  assert.equal(f.first.value, 'Ada');
  assert.equal(f.email.value, 'ada@example.com');
  assert.equal(f.city.value, 'London, UK');
  assert.equal(f.why.value, 'I build reliable data systems.');
  assert.equal(f.auth.selectedIndex, 1); // "Yes"
  assert.equal(f.sponsorNo.checked, true);
  assert.equal(f.sponsorYes.checked, false);
  assert.equal(res.filled, 3);
  assert.equal(res.answered, 3);
});

test('unknown or unconsented answers stay blank and are flagged for the human', () => {
  const f = form();
  const res = load(elementsOf(f))(PROFILE);
  assert.equal(f.gender.selectedIndex, 0);
  assert.equal(f.relocateYes.checked || f.relocateNo.checked, false);
  assert.deepEqual(
    [...res.needsYou].sort(),
    ['Are you willing to relocate?', 'Gender'].sort()
  );
  assert.match(f.gender.style.outline, /#f59e0b/);
  assert.match(f.relocateFieldset.style.outline, /#f59e0b/);
});

test('never overwrites a value the candidate already entered', () => {
  const f = form();
  load(elementsOf(f))(PROFILE);
  assert.equal(f.salary.value, '100k');
});

test('salary context and numeric input hints stay visible to the real field mapper', () => {
  const fields = [
    new FakeEl('input', { type: 'text', inputmode: 'numeric' }, { label: 'Expected salary' }),
    new FakeEl('input', { type: 'text', inputmode: 'decimal' }, { label: 'Expected salary' }),
    new FakeEl('input', { type: 'text', placeholder: 'EUR per year' }, { label: 'Expected salary' }),
    new FakeEl('input', { type: 'text', 'aria-label': 'Expected salary GBP per month' }, { label: 'Expected salary' }),
    new FakeEl('input', { type: 'text', placeholder: 'GBP per year' }, { label: 'Expected salary' }),
  ];
  const res = load(fields)(PROFILE);
  for (const field of fields.slice(0, 4)) {
    assert.equal(field.value, '');
    assert.match(field.style.outline, /#f59e0b/);
  }
  assert.equal(fields[4].value, 'GBP 90,000 per year');
  assert.equal(res.answered, 1);
  assert.ok(res.needsYou.includes('Expected salary'));
});

test('hidden ancestors prevent text, select and radio fill while visible controls and resume remain usable', () => {
  const cssHidden = new FakeEl('div', {}, { props: { style: { display: 'none' } } });
  const htmlHidden = new FakeEl('div', { hidden: '' });
  const invisible = new FakeEl('div', {}, { props: { style: { visibility: 'hidden' } } });
  const hiddenPhone = new FakeEl('input', { type: 'tel' }, { parent: cssHidden });
  const hiddenText = new FakeEl('textarea', {}, { label: 'Why do you want to work here?', parent: htmlHidden });
  const hiddenSelect = new FakeEl('select', {}, {
    label: 'Are you authorized to work in the UK?', parent: invisible,
    props: { options: [{ textContent: 'Select...', value: '' }, { textContent: 'Yes', value: 'yes' }], selectedIndex: 0 },
  });
  const hiddenRadio = new FakeEl('input', { type: 'radio', name: 'sponsor', value: 'No' }, {
    label: 'No', fieldset: fieldset('Will you require sponsorship in the UK?'), parent: cssHidden, props: { checked: false },
  });
  const visibleEmail = new FakeEl('input', { type: 'email' });
  const hiddenResume = new FakeEl('input', { type: 'file', id: 'resume' }, { parent: cssHidden, props: { files: [] } });
  const result = load([hiddenPhone, hiddenText, hiddenSelect, hiddenRadio, visibleEmail, hiddenResume])(PROFILE);
  assert.equal(hiddenPhone.value, '');
  assert.equal(hiddenText.value, '');
  assert.equal(hiddenSelect.selectedIndex, 0);
  assert.equal(hiddenRadio.checked, false);
  for (const el of [hiddenPhone, hiddenText, hiddenSelect, hiddenRadio]) assert.equal(el.events.length, 0);
  assert.equal(visibleEmail.value, 'ada@example.com');
  assert.equal(result.filled, 1);
  assert.equal(result.answered, 0);
  assert.equal(result.needsYou.length, 0);
  assert.equal(result.attached, 1);
  assert.equal(hiddenResume.files[0].name, 'Ada.pdf');
});

test('attaches the resume to the resume input only', () => {
  const f = form();
  const res = load(elementsOf(f))(PROFILE);
  assert.equal(res.attached, 1);
  assert.equal(f.resume.files[0].name, 'Ada.pdf');
  assert.equal(f.resume.files[0].type, 'application/pdf');
  assert.equal(f.cover.files.length, 0);
});

test('a profile without answers fills identity fields and flags every question', () => {
  const f = form();
  const res = load(elementsOf(f))({ fullName: 'Ada Lovelace' });
  assert.equal(f.first.value, 'Ada');
  assert.equal(f.auth.selectedIndex, 0);
  assert.equal(res.answered, 0);
  assert.equal(res.attached, 0);
  assert.ok(res.needsYou.length >= 4);
});

test('the content script contains no way to submit a form', () => {
  const src = read('content_script.js').replace(/\/\/.*$|\/\*[\s\S]*?\*\//gm, '');
  assert.doesNotMatch(src, /\.submit\s*\(|requestSubmit|type=submit|\[type="?submit/);
  assert.doesNotMatch(src, /\bform\b[^;\n]*\.click\(/);
});

test('popup and content scripts share field_mapping.js without global clashes', () => {
  // Classic scripts share one global lexical scope: a duplicate const would
  // throw a SyntaxError in the real extension.
  const ctx = { chrome: { runtime: { onMessage: { addListener() {} } } } };
  vm.createContext(ctx);
  vm.runInContext(read('field_mapping.js'), ctx);
  vm.runInContext(read('popup.js'), ctx);
  vm.runInContext(read('content_script.js'), ctx);
});


test('a real first select option is never overwritten', () => {
  const chosen = new FakeEl('select', {}, {
    label: 'Are you authorized to work in the UK?',
    props: { options: [{ textContent: 'No', value: 'no' }, { textContent: 'Yes', value: 'yes' }], selectedIndex: 0 },
  });
  const result = load([chosen])(PROFILE);
  assert.equal(chosen.selectedIndex, 0);
  assert.equal(result.answered, 0);
  assert.deepEqual(chosen.events, []);
});

test('unsafe eligibility questions are flagged without selecting an answer', () => {
  for (const label of [
    'Are you authorized to work in the United States?',
    'Are you authorized to work in the UK without visa sponsorship?',
    'Do you not require sponsorship in the UK?',
    'Are you authorized to work?',
  ]) {
    const select = new FakeEl('select', {}, {
      label,
      props: { options: [{ textContent: 'Select...', value: '' }, { textContent: 'Yes', value: 'yes' }, { textContent: 'No', value: 'no' }], selectedIndex: 0 },
    });
    const result = load([select])(PROFILE);
    assert.equal(select.selectedIndex, 0, label);
    assert.equal(result.answered, 0, label);
    assert.ok(result.needsYou.includes(label));
    assert.match(select.style.outline, /#f59e0b/);
  }
});
