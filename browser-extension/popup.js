// Check backend status
chrome.runtime.sendMessage({ action: "health" }, (response) => {
  const el = document.getElementById("status");
  if (response && response.status === "ok") {
    el.textContent = "online";
    el.className = "status online";
  } else {
    el.textContent = "offline";
    el.className = "status offline";
  }
});

function capture(prefix) {
  const textarea = document.getElementById("text");
  const resultEl = document.getElementById("result");
  let text = textarea.value.trim();

  if (!text) {
    resultEl.textContent = "Enter some text first";
    resultEl.style.color = "#f87171";
    return;
  }

  if (prefix) {
    text = `${prefix}: ${text}`;
  }

  chrome.runtime.sendMessage({ action: "capture", text: text }, (response) => {
    if (response && response.status === "sent") {
      resultEl.textContent = "Captured!";
      resultEl.style.color = "#4ade80";
      textarea.value = "";
    } else {
      resultEl.textContent = "Failed to capture";
      resultEl.style.color = "#f87171";
    }
  });
}

// Allow Enter to capture
document.getElementById("text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.metaKey) {
    capture("");
  }
});
