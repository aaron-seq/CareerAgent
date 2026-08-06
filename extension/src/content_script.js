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

/**
 * Attach the stored resume to a file input.
 *
 * File inputs cannot be assigned a path, but a DataTransfer built from a Blob
 * can be handed to `el.files`, which is how a real drop would arrive.
 */
function attachResume(resume) {
  if (!resume || !resume.data_b64) return 0;
  const fileInputs = document.querySelectorAll('input[type=file]');
  let attached = 0;
  fileInputs.forEach((el) => {
    if (el.disabled || (el.files && el.files.length)) return; // don't clobber
    try {
      const binary = atob(resume.data_b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const file = new File([bytes], resume.filename || 'resume.pdf', {
        type: resume.mime || 'application/pdf',
      });
      const dt = new DataTransfer();
      dt.items.add(file);
      el.files = dt.files;
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.style.outline = '2px solid #4caf50';
      attached += 1;
    } catch (err) {
      // A page may block programmatic file assignment; skip it quietly and
      // leave the input for the human.
    }
  });
  return attached;
}

/** Mark a control as touched by us. */
function highlight(el) {
  el.style.outline = '2px solid #4caf50';
}

/** Answer a <select> question. Returns true if an option was chosen. */
function answerSelect(el, answer) {
  const options = Array.from(el.options || []);
  if (!options.length) return false;
  let index = -1;
  if (answer.type === 'boolean') {
    index = CareerAgentFieldMapping.matchOptionForBoolean(
      options.map((o) => o.textContent || o.value),
      answer.value
    );
  } else {
    const wanted = String(answer.value).toLowerCase();
    index = options.findIndex((o) =>
      (o.textContent || o.value || '').toLowerCase().includes(wanted)
    );
  }
  if (index < 0) return false;
  el.selectedIndex = index;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  highlight(el);
  return true;
}

/** Answer a yes/no radio group. */
function answerRadioGroup(name, answer, root) {
  if (answer.type !== 'boolean') return false;
  const radios = Array.from(root.querySelectorAll(`input[type=radio][name="${name}"]`));
  if (!radios.length) return false;
  const labels = radios.map((r) => {
    if (r.labels && r.labels.length) return r.labels[0].textContent || '';
    return r.value || '';
  });
  const index = CareerAgentFieldMapping.matchOptionForBoolean(labels, answer.value);
  if (index < 0) return false;
  radios[index].checked = true;
  radios[index].dispatchEvent(new Event('change', { bubbles: true }));
  highlight(radios[index]);
  return true;
}

function fillForm(profile) {
  const mapping = CareerAgentFieldMapping;
  let filled = 0;
  let answered = 0;

  // 1. Plain identity fields.
  const inputs = document.querySelectorAll(
    'input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type])'
  );
  inputs.forEach((el) => {
    if (el.disabled || el.readOnly || el.value) return; // don't clobber
    const value = mapping.fillValueFor(describeField(el), profile);
    if (value) {
      setNativeValue(el, value);
      highlight(el);
      filled += 1;
      return;
    }
    // The same input might be an application question ("Salary expectation").
    const answer = mapping.answerFor(describeField(el), profile);
    if (answer && answer.type === 'text') {
      setNativeValue(el, answer.value);
      highlight(el);
      answered += 1;
    }
  });

  // 2. Textareas (cover note, "why this company").
  document.querySelectorAll('textarea').forEach((el) => {
    if (el.disabled || el.readOnly || el.value) return;
    const answer = mapping.answerFor(describeField(el), profile);
    if (answer && answer.type === 'text') {
      setNativeValue(el, answer.value);
      highlight(el);
      answered += 1;
    }
  });

  // 3. Selects (work authorization, sponsorship — usually dropdowns).
  document.querySelectorAll('select').forEach((el) => {
    if (el.disabled || el.selectedIndex > 0) return; // leave answered ones
    const answer = mapping.answerFor(describeField(el), profile);
    if (answer && answerSelect(el, answer)) answered += 1;
  });

  // 4. Radio groups, keyed by name so we only touch each group once.
  const seenGroups = new Set();
  document.querySelectorAll('input[type=radio]').forEach((el) => {
    const name = el.getAttribute('name');
    if (!name || seenGroups.has(name)) return;
    seenGroups.add(name);
    if (Array.from(document.querySelectorAll(`input[type=radio][name="${name}"]`)).some((r) => r.checked)) {
      return; // already answered
    }
    // A radio group's question usually sits on a fieldset/legend, so describe
    // the group via the first radio's label plus its name attribute.
    const answer = mapping.answerFor(describeField(el), profile);
    if (answer && answerRadioGroup(name, answer, document)) answered += 1;
  });

  const attached = attachResume(profile.resume);
  return { filled, answered, attached };
}

/** A small, dismissible banner so the user knows what just happened. */
function showBanner(result) {
  const existing = document.getElementById('careeragent-banner');
  if (existing) existing.remove();
  const bar = document.createElement('div');
  bar.id = 'careeragent-banner';
  bar.style.cssText =
    'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1f2937;' +
    'color:#fff;font:14px system-ui,sans-serif;padding:10px 16px;display:flex;' +
    'justify-content:space-between;align-items:center;box-shadow:0 1px 4px rgba(0,0,0,.3)';
  const parts = [`filled ${result.filled} field(s)`];
  if (result.answered) parts.push(`answered ${result.answered} question(s)`);
  if (result.attached) parts.push('attached your resume');
  bar.innerHTML =
    `<span>CareerAgent ${parts.join(', ')}. ` +
    `<strong>Review everything, then submit yourself.</strong></span>`;
  const close = document.createElement('button');
  close.textContent = 'Dismiss';
  close.style.cssText =
    'margin-left:16px;background:#4caf50;border:none;color:#fff;padding:4px 10px;' +
    'border-radius:4px;cursor:pointer';
  close.addEventListener('click', () => bar.remove());
  bar.appendChild(close);
  document.body.appendChild(bar);
  setTimeout(() => bar.remove(), 15000);
}

// Explicitly guarantee we never submit on the user's behalf.
function guardAgainstAutoSubmit() {
  // no-op by design: this script contains no form.submit() or click-submit.
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === 'CAREERAGENT_FILL') {
    guardAgainstAutoSubmit();
    const result = fillForm(msg.profile || {});
    if (result.filled || result.attached) showBanner(result);
    sendResponse(result);
  }
  return true;
});

/**
 * Auto-fill when the user lands on a supported application form.
 *
 * This is the "click Apply and it fills itself" path. It still never submits —
 * it types, attaches, and then hands control back to the human.
 */
function looksLikeApplicationForm() {
  if (!document.querySelector('form')) return false;
  // Require at least a couple of mappable fields so we don't fire on a
  // search box or a newsletter signup.
  const inputs = Array.from(
    document.querySelectorAll('input[type=text], input[type=email], input[type=tel]')
  );
  const mappable = inputs.filter((el) =>
    CareerAgentFieldMapping.mapFieldToProfileKey(describeField(el))
  );
  return mappable.length >= 2;
}

async function maybeAutofillOnLoad() {
  try {
    const { careeragent_autofill_on_load: enabled = true } =
      await chrome.storage.local.get('careeragent_autofill_on_load');
    if (!enabled) return;
    if (!looksLikeApplicationForm()) return;
    const profile = await chrome.runtime.sendMessage({
      type: 'CAREERAGENT_GET_PROFILE',
    });
    if (!profile || !profile.email) return; // nothing imported yet
    guardAgainstAutoSubmit();
    const result = fillForm(profile);
    if (result.filled || result.attached) showBanner(result);
  } catch (err) {
    // Never let autofill break the page the user is trying to apply on.
  }
}

// Forms on these ATS platforms render client-side, so wait for idle plus a
// short settle before looking for fields.
if (document.readyState === 'complete') {
  setTimeout(maybeAutofillOnLoad, 800);
} else {
  window.addEventListener('load', () => setTimeout(maybeAutofillOnLoad, 800));
}
