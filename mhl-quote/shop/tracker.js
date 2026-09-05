const form = document.getElementById("job-form");
const formError = document.getElementById("form-error");
const inboxError = document.getElementById("inbox-error");
const listBox = document.getElementById("job-list");
const jobsDir = document.getElementById("jobs-dir");
const inboxSelect = document.getElementById("inbox-select");
const editorTitle = document.getElementById("editor-title");

const FIELD_IDS = [
  "job_id",
  "rfq_id",
  "customer_name",
  "customer_email",
  "estimate_low_usd",
  "estimate_high_usd",
  "bid_usd",
  "deposit_usd",
  "chase_payment_url",
  "workflow_status",
  "payment_status",
  "notes",
];

let knownIds = new Set();

function money(value) {
  if (value == null || value === "") return "—";
  return `$${Number(value).toFixed(2)}`;
}

function band(low, high) {
  if (low == null && high == null) return "—";
  return `${money(low)}–${money(high)}`;
}

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function formPayload() {
  const data = {};
  for (const id of FIELD_IDS) {
    const el = document.getElementById(id);
    data[id] = el.value;
  }
  return data;
}

function fillForm(job) {
  for (const id of FIELD_IDS) {
    const el = document.getElementById(id);
    const value = job[id];
    el.value = value == null ? "" : String(value);
  }
  editorTitle.textContent = `Update ${job.job_id}`;
}

function clearForm() {
  form.reset();
  document.getElementById("workflow_status").value = "estimated";
  document.getElementById("payment_status").value = "unpaid";
  editorTitle.textContent = "Record / update a job";
  formError.textContent = "";
}

function renderJobs(jobs) {
  knownIds = new Set(jobs.map((job) => job.job_id));
  if (!jobs.length) {
    listBox.innerHTML =
      "<p class=\"hint\">No jobs yet. Record one after quotes@ or import a local inbox RFQ.</p>";
    return;
  }
  const rows = jobs
    .map((job) => {
      const chase = job.chase_payment_url
        ? `<span class="mono">pasted</span>`
        : "—";
      return `<tr>
        <td><button type="button" data-job="${job.job_id}">${job.job_id}</button></td>
        <td>${job.workflow_label}</td>
        <td>${job.payment_label}</td>
        <td>${band(job.estimate_low_usd, job.estimate_high_usd)}</td>
        <td>${money(job.bid_usd)}</td>
        <td>${money(job.deposit_usd)}</td>
        <td>${chase}</td>
      </tr>`;
    })
    .join("");
  listBox.innerHTML = `<table class="job-table">
    <thead><tr>
      <th>Job</th><th>Workflow</th><th>Payment</th><th>Estimate</th><th>Bid</th><th>Deposit</th><th>Chase</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  listBox.querySelectorAll("button[data-job]").forEach((button) => {
    button.addEventListener("click", () => {
      const job = jobs.find((item) => item.job_id === button.dataset.job);
      if (job) fillForm(job);
    });
  });
}

async function refresh() {
  const payload = await readJson(await fetch("/__shop/api/jobs"));
  jobsDir.textContent = `Ledger: ${payload.jobs_dir}`;
  renderJobs(payload.jobs);
  const inbox = await readJson(await fetch("/__shop/api/inbox"));
  inboxSelect.innerHTML = inbox.submissions.length
    ? inbox.submissions
        .map((name) => `<option value="${name}">${name}</option>`)
        .join("")
    : `<option value="">(no local inbox RFQs)</option>`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  const payload = formPayload();
  const exists = knownIds.has(payload.job_id);
  try {
    const response = await fetch(
      exists ? `/__shop/api/jobs/${encodeURIComponent(payload.job_id)}` : "/__shop/api/jobs",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    const job = await readJson(response);
    fillForm(job);
    await refresh();
  } catch (err) {
    formError.textContent = err.message;
  }
});

document.getElementById("advance-job").addEventListener("click", async () => {
  formError.textContent = "";
  const jobId = document.getElementById("job_id").value.trim();
  if (!jobId) {
    formError.textContent = "Save or select a job before advancing.";
    return;
  }
  try {
    const job = await readJson(
      await fetch(`/__shop/api/jobs/${encodeURIComponent(jobId)}/advance`, { method: "POST" })
    );
    fillForm(job);
    await refresh();
  } catch (err) {
    formError.textContent = err.message;
  }
});

document.getElementById("new-job").addEventListener("click", () => {
  clearForm();
});

document.getElementById("import-inbox").addEventListener("click", async () => {
  inboxError.textContent = "";
  const folder = inboxSelect.value;
  if (!folder) {
    inboxError.textContent = "No local inbox RFQ selected.";
    return;
  }
  try {
    const job = await readJson(
      await fetch("/__shop/api/jobs/from-inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inbox_folder: folder }),
      })
    );
    fillForm(job);
    await refresh();
  } catch (err) {
    inboxError.textContent = err.message;
  }
});

refresh().catch((err) => {
  formError.textContent = err.message;
});
