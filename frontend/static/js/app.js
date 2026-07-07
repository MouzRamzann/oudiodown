(() => {
  const form = document.getElementById("convert-form");
  const input = document.getElementById("reel-url");
  const button = document.getElementById("convert-btn");
  const resultPanel = document.getElementById("result-panel");
  const resultTitle = document.getElementById("result-title");
  const downloadLink = document.getElementById("download-link");
  const errorPanel = document.getElementById("error-panel");
  const yearEl = document.getElementById("year");

  if (yearEl) yearEl.textContent = new Date().getFullYear();

  const INSTAGRAM_URL_RE = /^https?:\/\/(www\.)?instagram\.com\/(reel|reels|p|tv)\/[\w-]+\/?/i;
  const POLL_INTERVAL_MS = 2000;
  const POLL_TIMEOUT_MS = 120000; // 2 minutes max

  function setLoading(isLoading, label = "Convert to MP3") {
    button.disabled = isLoading;
    button.classList.toggle("loading", isLoading);
    button.querySelector(".btn-label").textContent = isLoading ? "Converting" : label;
  }

  function showError(message) {
    resultPanel.hidden = true;
    errorPanel.hidden = false;
    errorPanel.textContent = message;
  }

  function showResult(title, downloadUrl) {
    errorPanel.hidden = true;
    resultPanel.hidden = false;
    resultTitle.textContent = title || "Your track";
    downloadLink.href = downloadUrl;
  }

  async function pollStatus(jobId) {
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

      let data;
      try {
        const resp = await fetch(`/api/status/${jobId}`);
        data = await resp.json();
      } catch {
        throw new Error("Lost connection while checking status. Please try again.");
      }

      if (data.status === "done") {
        return data;
      }
      if (data.status === "error") {
        throw new Error(data.error || "Conversion failed. Please try again.");
      }
      // "pending" or "processing" — keep polling
    }

    throw new Error("Conversion timed out. Please try again.");
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
      // Step 1 — start the job
      const startResp = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      const startData = await startResp.json().catch(() => ({}));
      if (!startResp.ok) {
        throw new Error(startData.detail || "Could not start conversion.");
      }

      // Step 2 — poll until done
      const result = await pollStatus(startData.job_id);
      showResult(result.title, result.download_url);
    } catch (err) {
      showError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false, "Convert to MP3");
    }
  });
})();
