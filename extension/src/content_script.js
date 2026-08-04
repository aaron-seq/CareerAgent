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

function fillForm(profile) {
  const inputs = document.querySelectorAll(
    'input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type])'
  );
  let filled = 0;
  inputs.forEach((el) => {
    if (el.disabled || el.readOnly || el.value) return; // don't clobber
    const value = CareerAgentFieldMapping.fillValueFor(describeField(el), profile);
    if (value) {
      setNativeValue(el, value);
      el.style.outline = '2px solid #4caf50'; // visual confirmation
      filled += 1;
    }
  });
  const attached = attachResume(profile.resume);
  return { filled, attached };
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
  const resumeNote = result.attached ? ` and attached your resume` : '';
  bar.innerHTML =
    `<span>CareerAgent filled ${result.filled} field(s)${resumeNote}. ` +
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
