import { login } from "../api/traccar.js";

export function render(container, onSuccess) {
  container.innerHTML = `
    <div class="screen screen-login is-active">
      <div class="login-wrap">
        <span class="hero-emoji">🐱</span>
        <h1>FindMyCat</h1>
        <p>Sign in to track your cat.</p>
        <form id="lf" novalidate>
          <div class="field"><label for="em">Email</label><input type="email" id="em" autocomplete="email" placeholder="you@example.com"></div>
          <div class="field"><label for="pw">Password</label><input type="password" id="pw" autocomplete="current-password" placeholder="Password"></div>
          <button class="btn-primary" id="lb" type="submit">Sign In</button>
        </form>
        <div class="login-error" id="le"></div>
      </div>
    </div>
  `;

  const form = container.querySelector("#lf");
  const btn = container.querySelector("#lb");
  const emailInput = container.querySelector("#em");
  const pwInput = container.querySelector("#pw");
  const errorEl = container.querySelector("#le");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    btn.innerHTML = '<span class="spinner"></span> Signing in…';
    btn.disabled = true;
    errorEl.classList.remove("is-visible");

    try {
      await login(emailInput.value, pwInput.value);
      onSuccess();
    } catch (err) {
      const msg = err?.message || "Sign in failed. Please try again.";
      btn.textContent = "Sign In";
      btn.disabled = false;
      errorEl.textContent = msg;
      errorEl.classList.add("is-visible");
    }
  });
}
