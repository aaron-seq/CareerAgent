/**
 * Content script: fill visible form fields from the saved profile.
 *
 * Runs only when the user triggers it (message from the popup). It fills
 * identity fields, answers screening questions the candidate has answered
 * (text inputs, textareas, <select>s, yes/no radio groups), attaches the
 * resume to the resume upload, and outlines every recognised question it
 * could NOT answer in amber so the human answers it. It dispatches
 * input/change events so React-based ATS forms register the change.
 *
 * It NEVER clicks submit -- the human reviews and submits.
 */

'use strict';

/* global CareerAgentFieldMapping, chrome, DataTransfer, File */

const FILLED_OUTLINE = '2px solid #4caf50';
const NEEDS_YOU_OUTLINE = '2px solid #f59e0b';

function textOf(node) {
  return node ? (node.textContent || '').trim() : '';
}

function describeField(el) {
  let label = '';
  if (el.labels && el.labels.length) {
    label = el.labels[0].textContent || '';
  } else if (el.getAttribute('aria-labelledby')) {
    const ref = document.getElementById(el.getAttribute('aria-labelledby'));
    if (ref) label = ref.textContent || '';
  }
  return {
    autocomplete: el.getAttribute('autocomplete') || '',
    id: el.id || '',
    name: el.getAttribute('name') || '',
    label,
    ariaLabel: el.getAttribute('aria-label') || '',
    placeholder: el.getAttribute('placeholder') || '',
    type: el.getAttribute('type') || '',
  };
}

/**
 * A radio group's question lives on its fieldset legend or radiogroup label,
 * not on the individual "Yes"/"No" labels.
 */
function describeRadioGroup(radio) {
  const field = describeField(radio);
  const fieldset = radio.closest('fieldset');
  const group = radio.closest('[role=radiogroup]');
  let question = '';
  if (fieldset) question = textOf(fieldset.querySelector('legend'));
  if (!question && group) {
    const ref = group.getAttribute('aria-labelledby');
    question = group.getAttribute('aria-label') || textOf(ref && document.getElementById(ref));
  }
  return { ...field, label: question || field.label, autocomplete: '', type: '' };
}

function setNativeValue(el, value) {
  // React overrides the value setter; use the prototype setter so the
  // framework observes the change.
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  if (desc && desc.set) {
    desc.set.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function newResult() {
  return { filled: 0, answered: 0, attached: 0, needsYou: [] };
}

function flagForHuman(el, field, result) {
  el.style.outline = NEEDS_YOU_OUTLINE;
  const label = (field.label || field.ariaLabel || field.name || 'question').trim().slice(0, 120);
  if (!result.needsYou.includes(label)) result.needsYou.push(label);
}

function fillTextLike(el, result) {
  const field = describeField(el);
  const decision = CareerAgentFieldMapping.classifyField(field, profileRef);
  if (!decision) return;
  // Custom-dropdown widgets (React-select comboboxes, seen on real Greenhouse
  // forms) need a real option chosen, not typed text: never type into them,
  // but do flag a recognised question for the human.
  if (el.getAttribute('role') === 'combobox') {
    if (decision.kind === 'question') flagForHuman(el, field, result);
    return;
  }
  if (decision.kind === 'profile') {
    if (decision.value && el.tagName !== 'TEXTAREA') {
      setNativeValue(el, decision.value);
      el.style.outline = FILLED_OUTLINE;
      result.filled += 1;
    }
    return;
  }
  const answer = decision.answer;
  if (!answer) {
    flagForHuman(el, field, result);
    return;
  }
  setNativeValue(el, answer.type === 'boolean' ? (answer.value ? 'Yes' : 'No') : answer.value);
  el.style.outline = FILLED_OUTLINE;
  result.answered += 1;
}

function fillSelect(el, result) {
  const field = describeField(el);
  if (!CareerAgentFieldMapping.mapFieldToQuestion(field)) return;
  const answer = CareerAgentFieldMapping.answerFor(field, profileRef);
  const texts = Array.from(el.options || []).map((o) => o.textContent || o.value || '');
  let index = -1;
  if (answer) {
    index =
      answer.type === 'boolean'
        ? CareerAgentFieldMapping.matchOptionForBoolean(texts, answer.value)
        : CareerAgentFieldMapping.matchOptionForText(texts, answer.value);
  }
  if (index < 0) {
    flagForHuman(el, field, result);
    return;
  }
  el.selectedIndex = index;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.style.outline = FILLED_OUTLINE;
  result.answered += 1;
}

function fillRadioGroup(radios, result) {
  const field = describeRadioGroup(radios[0]);
  if (!CareerAgentFieldMapping.mapFieldToQuestion(field)) return;
  const answer = CareerAgentFieldMapping.answerFor(field, profileRef);
  const texts = radios.map((r) => (r.labels && r.labels.length ? textOf(r.labels[0]) : r.value));
  let index = -1;
  if (answer) {
    index =
      answer.type === 'boolean'
        ? CareerAgentFieldMapping.matchOptionForBoolean(texts, answer.value)
        : CareerAgentFieldMapping.matchOptionForText(texts, answer.value);
  }
  const anchor = radios[0].closest('fieldset') || radios[0];
  if (index < 0) {
    flagForHuman(anchor, field, result);
    return;
  }
  // Selecting a radio option the way a person does: click() checks it and
  // fires the input/change events React listens for. A radio input has no
  // submit behaviour, so this cannot send the form.
  radios[index].click();
  anchor.style.outline = FILLED_OUTLINE;
  result.answered += 1;
}

/**
 * Attach the resume to the resume upload only (never a cover-letter input).
 * File inputs can't take a path, but a DataTransfer built from bytes can be
 * assigned to `el.files`, which is how a real drop arrives.
 */
function attachResume(resume, result) {
  const decoded = CareerAgentFieldMapping.decodeResume(resume);
  if (!decoded) return;
  document.querySelectorAll('input[type=file]').forEach((el) => {
    if (el.disabled || (el.files && el.files.length)) return; // don't clobber
    if (!CareerAgentFieldMapping.isResumeField(describeField(el))) return;
    try {
      const file = new File([decoded.bytes], decoded.filename, { type: decoded.mime });
      const dt = new DataTransfer();
      dt.items.add(file);
      el.files = dt.files;
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.style.outline = FILLED_OUTLINE;
      result.attached += 1;
    } catch (err) {
      // The page blocked programmatic assignment: leave it for the human.
    }
  });
}

// The profile for the current pass; set by fillOnce, read by the helpers.
let profileRef = {};

function fillOnce(profile) {
  profileRef = profile || {};
  const result = newResult();

  document
    .querySelectorAll(
      'input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type]), textarea'
    )
    .forEach((el) => {
      if (el.disabled || el.readOnly || el.value) return; // don't clobber
      fillTextLike(el, result);
    });

  document.querySelectorAll('select').forEach((el) => {
    if (el.disabled || el.selectedIndex > 0) return; // already answered
    fillSelect(el, result);
  });

  const groups = new Map();
  document.querySelectorAll('input[type=radio]').forEach((el) => {
    const name = el.getAttribute('name');
    if (!name || el.disabled) return;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(el);
  });
  groups.forEach((radios) => {
    if (radios.some((r) => r.checked)) return; // already answered
    fillRadioGroup(radios, result);
  });

  attachResume(profileRef.resume, result);
  return result;
}

function fillForm(profile) {
  const result = fillOnce(profile);
  // ponytail: some ATS forms (observed live on Greenhouse) still finish a
  // React hydration-mismatch recovery shortly after document_idle, which can
  // silently wipe a field we just filled. One delayed re-pass self-heals
  // that race; it's not a MutationObserver watch, so a slower/second
  // recovery after ~800ms could still win -- upgrade to an observer if that
  // shows up in practice.
  setTimeout(() => fillOnce(profile), 800);
  return result;
}

// Explicitly guarantee we never submit on the user's behalf.
function guardAgainstAutoSubmit() {
  // no-op by design: this script contains no form.submit() or click-submit.
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === 'CAREERAGENT_FILL') {
    guardAgainstAutoSubmit();
    sendResponse(fillForm(msg.profile || {}));
  }
  return true;
});
