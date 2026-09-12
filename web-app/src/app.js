import { render as renderLogin } from "./screens/login.js"
import { render as renderHome, destroy as destroyHome } from "./screens/home.js"
import { getSession } from "./api/traccar.js"

function route(hash) {
  const app = document.getElementById("app")
  destroyHome()
  if (hash === "#home") {
    renderHome(app)
  } else {
    renderLogin(app, () => { location.hash = "#home" })
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("service-worker.js").catch((e) => console.warn("Service worker registration failed:", e))
  }

  window.addEventListener("hashchange", e => route(new URL(e.newURL).hash))

  try {
    await getSession()
    // If hash already matches, hashchange won't fire — call route() directly.
    // If hash differs, set it and let hashchange call route() — don't call both.
    if (location.hash === "#home") route("#home")
    else location.hash = "#home"
  } catch {
    if (location.hash === "#login") route("#login")
    else location.hash = "#login"
  }
})
