const form = document.querySelector("#login-form");
const errorBox = document.querySelector("#login-error");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#login-submit");
  button.disabled = true;
  errorBox.classList.add("hidden");
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.username.value, password: form.password.value }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(typeof detail.detail === "string" ? detail.detail : "Could not sign in.");
    }
    window.location.href = "/";
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
    form.password.value = "";
  } finally {
    button.disabled = false;
  }
});
