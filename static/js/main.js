// =====================================================
//  CAMPUS HARDWARE — MAIN JS
// =====================================================

// ── Password toggle ──────────────────────────────────
function togglePassword(fieldId, btn) {
  const field = document.getElementById(fieldId);
  if (!field) return;
  const isHidden = field.type === 'password';
  field.type = isHidden ? 'text' : 'password';
  // Swap icon
  btn.innerHTML = isHidden
    ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
}

// ── Cart badge updater ───────────────────────────────
function updateCartBadge(count) {
  const badge = document.querySelector('.cart-badge');
  const link  = document.querySelector('.nav-cart');
  if (!link) return;

  if (count > 0) {
    if (badge) {
      badge.textContent = count;
    } else {
      const b = document.createElement('span');
      b.className = 'cart-badge';
      b.textContent = count;
      link.appendChild(b);
    }
  } else {
    badge?.remove();
  }
}

// ── Auto-dismiss flash messages after 5s ────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.flash').forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity .4s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  });
});
