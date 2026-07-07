(() => {
  const form = document.getElementById("convert-form");
  const input = document.getElementById("reel-url");
  const button = document.getElementById("convert-btn");
  const resultPanel = document.getElementById("result-panel");
  const resultTitle = document.getElementById("result-title");
  const downloadLink = document.getElementById("download-link");
  const errorPanel = document.getElementById("error-panel");
  const yearEl = document.getElementById("year");

  if (yearEl) {
    yearEl.textContent = new Date().getFullYear();
  }

  const INSTAGRAM_URL_RE = /^https?:\/\/(www\.)?instagram\.com\/(reel|reels|p|tv)\/[\w-]+\/?/i;

  function setLoading(isLoading) {
    button.disabled = isLoading;
    button.classList.toggle("loading", isLoading);
  }

  function showError(message) {
    resultPanel.hidden = true;
    errorPanel.hidden = false;
    errorPanel.textContent = message;
  }

  function showResult(title, downloadUrl) {
    errorPanel.hidden = true;
    resultPanel.hidden = false;
    resultTitle.textContent = title;
    downloadLink.href = downloadUrl;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = input.value.trim();

    if (!INSTAGRAM_URL_RE.test(url)) {
      showError("Please paste a valid public Instagram Reel or post URL.");
      return;
    }

    setLoading(true);
    errorPanel.hidden = true;
    resultPanel.hidden = true;

    try {
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.detail || "Conversion failed. Please try again.");
      }

      showResult(data.title || "Your track", data.download_url);
    } catch (err) {
      showError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  });
})();
