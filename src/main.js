// Humanarties — signup form handling
// Wires every .signup-form on the page to POST /api/subscribe

(function () {
  const forms = document.querySelectorAll('.signup-form');

  forms.forEach((form) => {
    form.addEventListener('submit', handleSubmit);
  });

  async function handleSubmit(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const emailInput = form.querySelector('input[type="email"]');
    const honeypot = form.querySelector('input[name="company"]');
    const button = form.querySelector('button[type="submit"]');
    const status = form.querySelector('.form-status');
    const source = form.dataset.form || 'unknown';

    const email = emailInput.value.trim();

    if (!email || !isValidEmail(email)) {
      setStatus(status, 'Enter a valid email address.', 'error');
      emailInput.focus();
      return;
    }

    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="btn-label">Joining…</span>';
    setStatus(status, '', null);

    try {
      const response = await fetch('/api/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          company: honeypot ? honeypot.value : '',
          source
        })
      });

      const data = await response.json().catch(() => ({}));

      if (response.ok) {
        setStatus(status, data.message || "You're on the list — you'll be one of the first to know when we launch!", 'success');
        form.reset();
      } else {
        setStatus(status, data.message || 'Something went wrong. Please try again.', 'error');
      }
    } catch (err) {
      setStatus(status, 'Network error — please try again in a moment.', 'error');
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
    }
  }

  function setStatus(el, message, state) {
    if (!el) return;
    el.textContent = message;
    if (state) {
      el.setAttribute('data-state', state);
    } else {
      el.removeAttribute('data-state');
    }
  }

  function isValidEmail(value) {
    // Simple, permissive check — the real validation happens server-side.
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }
})();
