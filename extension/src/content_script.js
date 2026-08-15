/**
 * Content script: fill visible form fields from the saved profile.
 *
 * Runs only when the user triggers it (message from the popup). It fills
 * fields and dispatches input/change events so React-based ATS forms register
 * the change. It NEVER clicks submit -- the human reviews and submits.
 */

'use strict';

/* global CareerAgentFieldMapping, chrome */

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

function fillOnce(profile) {
  const inputs = document.querySelectorAll(
    'input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type])'
  );
  let filled = 0;
  inputs.forEach((el) => {
    if (el.disabled || el.readOnly || el.value) return; // don't clobber
    // Custom-dropdown widgets (React-select style comboboxes, seen on real
    // Greenhouse forms for Country/custom questions) need a real option
    // selected, not just a text value -- forcing text in leaves them looking
    // filled without actually registering a valid selection.
    if (el.getAttribute('role') === 'combobox') return;
    const value = CareerAgentFieldMapping.fillValueFor(describeField(el), profile);
    if (value) {
      setNativeValue(el, value);
      el.style.outline = '2px solid #4caf50'; // visual confirmation
      filled += 1;
    }
  });
  return filled;
}

function fillForm(profile) {
  const filled = fillOnce(profile);
  // ponytail: some ATS forms (observed live on Greenhouse) still finish a
  // React hydration-mismatch recovery shortly after document_idle, which can
  // silently wipe a field we just filled. One delayed re-pass self-heals
  // that race; it's not a MutationObserver watch, so a slower/second
  // recovery after ~800ms could still win -- upgrade to an observer if that
  // shows up in practice.
  setTimeout(() => fillOnce(profile), 800);
  return filled;
}

// Explicitly guarantee we never submit on the user's behalf.
function guardAgainstAutoSubmit() {
  // no-op by design: this script contains no form.submit() or click-submit.
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === 'CAREERAGENT_FILL') {
    guardAgainstAutoSubmit();
    const filled = fillForm(msg.profile || {});
    sendResponse({ filled });
  }
  return true;
});
