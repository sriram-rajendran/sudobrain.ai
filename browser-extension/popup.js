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

let activeMeta = {};

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs && tabs[0];
  activeMeta = {
    sourceUrl: tab?.url || "",
    sourceTitle: tab?.title || "",
  };
  const source = document.getElementById("source");
  source.textContent = activeMeta.sourceTitle || activeMeta.sourceUrl || "No page metadata";
  source.title = activeMeta.sourceUrl;
});

function loadHistory() {
  chrome.runtime.sendMessage({ action: "history" }, (response) => {
    const el = document.getElementById("history");
    const history = response?.history || [];
    el.innerHTML = history.length
      ? history.map((h) => `<div class="history-item"><strong>${h.type}</strong>: ${escapeHtml(h.text || "")}</div>`).join("")
      : '<div class="history-item">No captures yet</div>';
  });
}

function capture(prefix) {
  const textarea = document.getElementById("text");
  const resultEl = document.getElementById("result");
  const project = document.getElementById("project").value.trim();
  const person = document.getElementById("person").value.trim();
  let text = textarea.value.trim();

  if (!text) {
    resultEl.textContent = "Enter some text first";
    resultEl.style.color = "#f87171";
    return;
  }

  if (prefix) {
    text = `${prefix}: ${text}`;
  }

  chrome.runtime.sendMessage({
    action: "capture",
    text: text,
    meta: { ...activeMeta, project, person },
  }, (response) => {
    if (response && response.status === "sent") {
      resultEl.textContent = "Captured!";
      resultEl.style.color = "#4ade80";
      textarea.value = "";
      loadHistory();
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

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

loadHistory();
