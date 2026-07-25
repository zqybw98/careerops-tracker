# CareerOps Capture Chrome Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing privacy-first Autofill Popup with a review-first Side Panel that extracts a job draft and sends it only to the authenticated local CareerOps Bridge.

**Architecture:** The existing Popup remains the Autofill entry point and adds one user-triggered Capture command. Small plain-JavaScript capture modules separate target-Tab state, page extraction, API requests, and reviewed draft state. A tab-specific Side Panel owns visible Local Network Access, duplicate preview, explicit confirmation, and safe retries.

**Tech Stack:** Chrome Manifest V3, plain JavaScript, HTML, CSS, `chrome.sidePanel`, `chrome.scripting`, `chrome.storage.local`, `chrome.storage.session`, standard Node syntax/fake-DOM smoke tests without npm dependencies.

## Global Constraints

- Execute this plan from the `job-application-autofill-extension` repository
  root.
- Follow the approved CareerOps Capture Extension Design in the
  `careerops-tracker` repository.
- Preserve the current Popup Autofill, field detection, profile storage, and
  manual dashboard behavior.
- Use plain JavaScript, HTML, and CSS; add no React, npm, bundler, or dependency.
- Keep `activeTab`; do not add `<all_urls>`.
- Add only optional `http://127.0.0.1/*` host permission and hardcode runtime
  requests to exactly `http://127.0.0.1:8765`.
- The production API client must not accept a configurable origin or port.
- Store the bearer token only in `chrome.storage.local` after setting
  `TRUSTED_CONTEXTS`; content scripts and injected extractors must never receive
  it.
- Store only target Tab ID, URL, and capture time in
  `chrome.storage.session`; never store token or page content there.
- Record the target `{tabId, url}` during the Popup click and never substitute
  a later active Tab.
- Saving and updating are always explicit user actions. Never auto-submit,
  auto-save, upload files, read Gmail, or call any cloud service.
- `edited_fields` comes only from direct user edits and is sent uniquely in
  stable sorted order.
- Retry one immutable payload with the same UUID; any edit after a save attempt
  starts a new request ID.
- Use synthetic pages and data for all tests and screenshots.
- Do not commit or push until the user separately approves reviewed changes.

---

### Task 1: Add Manifest Permissions and Trusted Capture Storage

**Files:**
- Modify: `manifest.json`
- Modify: `src/storage.js`
- Modify: `src/options.html`
- Modify: `src/options.js`
- Create: `test/capture-storage-test.js`

**Interfaces:**
- Produces: `JobApplicationStorage.initializeTrustedStorage() -> Promise<void>`
- Produces: `JobApplicationStorage.getCaptureSettings() -> Promise<{token: string}>`
- Produces: `JobApplicationStorage.saveCaptureToken(token: string) -> Promise<void>`
- Produces: `JobApplicationStorage.clearCaptureToken() -> Promise<void>`
- Produces: `JobApplicationStorage.saveCaptureTarget(target) -> Promise<void>`
- Produces: `JobApplicationStorage.getCaptureTarget() -> Promise<object | null>`
- Produces: `JobApplicationStorage.clearCaptureTarget() -> Promise<void>`.

- [ ] **Step 1: Write a failing storage smoke test**

Use Node's standard `assert` and `vm` modules with a fake `chrome.storage`
implementation. Assert:

- `chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"})`
  occurs before any local read/write;
- existing Profile and Settings methods still work afterward;
- token reads/writes use local storage;
- target reads/writes use session storage;
- token and target are never stored in the same object;
- default content-script access is never enabled.

- [ ] **Step 2: Run syntax and smoke tests and verify failure**

Run:

```powershell
node --check src/storage.js
node test/capture-storage-test.js
```

Expected: smoke test FAIL because Capture storage APIs do not exist.

- [ ] **Step 3: Update the manifest**

Preserve the existing Popup and add:

```json
{
  "minimum_chrome_version": "116",
  "permissions": ["storage", "activeTab", "scripting", "sidePanel"],
  "optional_host_permissions": ["http://127.0.0.1/*"],
  "side_panel": {
    "default_path": "src/sidepanel.html"
  }
}
```

Do not add a background service worker unless a later test proves it necessary.
Do not enable `openPanelOnActionClick`.

- [ ] **Step 4: Implement trusted storage initialization**

Create one initialization Promise so simultaneous callers do not reorder
access:

```javascript
let trustedStorageReady;

function initializeTrustedStorage() {
  trustedStorageReady ||= chrome.storage.local.setAccessLevel({
    accessLevel: "TRUSTED_CONTEXTS"
  });
  return trustedStorageReady;
}
```

Every local getter/setter must await it. Keep existing Profile/Settings keys
and data shape unchanged. Use `chrome.storage.session` only for:

```javascript
{
  captureTarget: {
    tabId: 123,
    url: "https://example.com/jobs/1",
    capturedAt: "2026-07-25T12:00:00.000Z"
  }
}
```

- [ ] **Step 5: Add the pairing controls to Options**

Add a visually separate `CareerOps Capture` section with:

- fixed endpoint text;
- token password field;
- `Save pairing token`;
- `Clear pairing token`;
- `Grant local connection permission`;
- status region using `textContent`.

Request the optional host permission only from the explicit grant button:

```javascript
chrome.permissions.request({
  origins: ["http://127.0.0.1/*"]
});
```

Do not send a Bridge request from Options; the visible Side Panel owns health
and pair confirmation.

- [ ] **Step 6: Run storage and manifest checks**

Run:

```powershell
node --check src/storage.js
node --check src/options.js
node test/capture-storage-test.js
node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8')); console.log('manifest ok')"
```

Expected: PASS.

- [ ] **Step 7: Review and commit**

Suggested commit:

```powershell
git add manifest.json src/storage.js src/options.html src/options.js test/capture-storage-test.js
git commit -m "Add trusted CareerOps pairing storage"
```

Do not push.

### Task 2: Add Pure Job Extraction and Draft Intent Tracking

**Files:**
- Create: `src/capture/jobExtractor.js`
- Create: `src/capture/captureDraft.js`
- Create: `test/job-capture-test.js`
- Create: `test/job-capture-fixtures.html`

**Interfaces:**
- Produces: `JobCaptureExtractor.extract(document, pageUrl, localDate) -> CaptureDraft`
- Produces: `JobCaptureDraft.create(extracted) -> DraftController`
- Produces: `DraftController.updateFromUser(field, value) -> void`
- Produces: `DraftController.refresh(extracted) -> void`
- Produces: `DraftController.toPreviewPayload() -> object`
- Produces: `DraftController.toConfirmedPayload(options) -> object`.

- [ ] **Step 1: Write failing extraction tests**

Use a minimal fake DOM and synthetic fixtures to cover:

- direct `JobPosting` JSON-LD;
- `@graph` containing `JobPosting`;
- hiring organization text/object;
- title, locality/region/country, and canonical URL;
- generic `h1`, company metadata, and visible location fallback;
- missing Company or Location;
- page URL retained only as `source_link`;
- raw HTML, cookies, credentials, and full page text never returned;
- `JobPosting.datePosted` ignored for `application_date`;
- supplied local Capture date used for `application_date`;
- ATS fixture hooks for Personio and Workday without modifying Autofill
  adapters.

- [ ] **Step 2: Write failing draft-controller tests**

Cover:

- extraction initializes fields without edited intent;
- direct `updateFromUser("location", "Berlin")` records `location`;
- repeated edits do not duplicate names;
- confirmed payload sorts `edited_fields`;
- `refresh()` replaces baseline and clears edited intent;
- preview omits `edited_fields`;
- retry locks one payload and UUID;
- changing a locked draft requires a fresh explicit capture.

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
node test/job-capture-test.js
```

Expected: FAIL because the capture modules do not exist.

- [ ] **Step 4: Implement bounded extraction**

Expose an IIFE global, matching current project style:

```javascript
globalThis.JobCaptureExtractor = Object.freeze({
  extract
});
```

Return only:

```javascript
{
  company: "",
  role: "",
  location: "",
  application_date: localDate,
  status: "Applied",
  source_link: pageUrl,
  notes: ""
}
```

Parse only bounded structured and visible metadata. Do not serialize the page,
forms, or arbitrary body text.

- [ ] **Step 5: Implement edited-field tracking**

Use a Set internally and allow only:

```javascript
const EDITABLE_FIELDS = new Set([
  "company",
  "role",
  "location",
  "application_date",
  "status",
  "source_link",
  "notes"
]);
```

Only `updateFromUser()` may add to it. Normalize the confirmed payload to a
unique sorted array. Generate UUID v4 with `crypto.randomUUID()` at the first
explicit save attempt and retain both UUID and immutable payload for retry.

- [ ] **Step 6: Run extraction tests**

Run:

```powershell
node --check src/capture/jobExtractor.js
node --check src/capture/captureDraft.js
node test/job-capture-test.js
```

Expected: PASS.

- [ ] **Step 7: Review and commit**

Suggested commit:

```powershell
git add src/capture/jobExtractor.js src/capture/captureDraft.js test/job-capture-test.js test/job-capture-fixtures.html
git commit -m "Add reviewed job capture extraction"
```

Do not push.

### Task 3: Add a Fixed-Origin CareerOps API Client

**Files:**
- Create: `src/capture/careerOpsClient.js`
- Create: `test/careerops-client-test.js`

**Interfaces:**
- Produces: `CareerOpsClient.health({signal}) -> Promise<object>`
- Produces: `CareerOpsClient.confirmPairing(token, {signal}) -> Promise<object>`
- Produces: `CareerOpsClient.preview(token, payload, {signal}) -> Promise<object>`
- Produces: `CareerOpsClient.save(token, payload, {signal}) -> Promise<object>`
- Produces: `CareerOpsClientError(code, status, message, field)`.

- [ ] **Step 1: Write failing client tests**

Inject a fake `fetch` function and cover:

- every URL begins exactly with `http://127.0.0.1:8765/api/v1/`;
- no exported constructor or setting accepts another origin or port;
- any page-provided URL remains only in JSON `source_link`;
- health omits bearer header;
- pair/preview/save include bearer and API version headers;
- request content type is JSON;
- five-second AbortController timeout;
- missing or unsupported API version parsed as `400`
  `unsupported_api_version`;
- response body parsed into distinct offline, timeout, `401`, `403`, `404`,
  `409`, `413`, `415`, `422`, `500`, and `503` errors;
- token absent from thrown error messages;
- retry sends byte-equivalent JSON for the same immutable payload.

Explicitly assert that no request can be constructed for:

```text
http://127.0.0.1:9999
http://localhost:8765
https://careerops-tracker.streamlit.app
https://example.com
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
node test/careerops-client-test.js
```

Expected: FAIL because `careerOpsClient.js` does not exist.

- [ ] **Step 3: Implement the client**

Keep the origin private and immutable:

```javascript
const CAREEROPS_API_ORIGIN = "http://127.0.0.1:8765";
const API_VERSION = "1";
const REQUEST_TIMEOUT_MS = 5000;
```

Expose endpoint methods only, not a generic `request(url)` method. Health is
anonymous. Authenticated methods add:

```text
Authorization: Bearer <token>
X-CareerOps-API-Version: 1
Content-Type: application/json
```

Use safe generic client errors and never include token text. Preserve the
server's machine-readable error code for every documented HTTP status so the
Side Panel never has to infer behavior from an error message.

- [ ] **Step 4: Run client tests**

Run:

```powershell
node --check src/capture/careerOpsClient.js
node test/careerops-client-test.js
```

Expected: PASS.

- [ ] **Step 5: Review and commit**

Suggested commit:

```powershell
git add src/capture/careerOpsClient.js test/careerops-client-test.js
git commit -m "Add fixed-origin CareerOps API client"
```

Do not push.

### Task 4: Preserve the Popup and Lock the Capture Target

**Files:**
- Modify: `src/popup.html`
- Modify: `src/popup.js`
- Create: `test/capture-target-test.js`

**Interfaces:**
- Produces Popup command `Capture current job`.
- Consumes `JobApplicationStorage.saveCaptureTarget(...)`.
- Opens `chrome.sidePanel.open({tabId})`.

- [ ] **Step 1: Write a failing Popup target test**

Use fake DOM and Chrome APIs to assert:

- existing `Fill current page`, `Show detected fields`, `Open profile`, and
  `Open dashboard` handlers remain installed;
- Capture rejects missing, `chrome://`, `chrome-extension://`, and `file://`
  targets;
- one Capture click stores the active Tab ID and exact URL before calling
  `sidePanel.open({tabId})`;
- a later active-Tab switch does not modify the stored target;
- no token is read or passed from Popup capture code.

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
node test/capture-target-test.js
```

Expected: FAIL because the Capture command does not exist.

- [ ] **Step 3: Add the Popup command**

Add one secondary button:

```html
<button id="captureJob" type="button">Capture current job</button>
```

In its click handler:

```javascript
const tab = await getActiveTab();
await JobApplicationStorage.saveCaptureTarget({
  tabId: tab.id,
  url: tab.url,
  capturedAt: new Date().toISOString()
});
await chrome.sidePanel.open({tabId: tab.id});
```

Validate the scheme first. Do not query the active Tab again after opening the
panel and do not change existing Autofill handlers.

- [ ] **Step 4: Run Popup regression checks**

Run:

```powershell
node --check src/popup.js
node test/capture-target-test.js
```

Expected: PASS.

- [ ] **Step 5: Review and commit**

Suggested commit:

```powershell
git add src/popup.html src/popup.js test/capture-target-test.js
git commit -m "Add explicit current-job capture command"
```

Do not push.

### Task 5: Build the Review-First Side Panel

**Files:**
- Create: `src/sidepanel.html`
- Create: `src/sidepanel.css`
- Create: `src/sidepanel.js`
- Create: `test/sidepanel-smoke-test.js`

**Interfaces:**
- Consumes: Capture storage, extractor, draft controller, and API client.
- Produces visible Connect, Preview, Duplicate Resolution, Save, Retry, and
  success states.

- [ ] **Step 1: Write a failing Side Panel state test**

Use a fake DOM, fake `chrome.tabs`, fake `chrome.scripting`, fake Permissions
API, and fake API client. Cover:

- recorded target Tab is loaded by ID;
- actual URL must exactly match recorded URL before extraction;
- changing active Tab does not redirect extraction;
- closed/navigated target asks for a fresh Popup click;
- extraction function receives no token;
- first visible health request owns LNA prompting;
- `loopback-network` query with `local-network-access` fallback;
- denied permission differs from Bridge offline, timeout, and unauthorized;
- initial extracted fields do not populate `edited_fields`;
- input/change events do populate `edited_fields`;
- duplicate choices are `use_existing`, `create_anyway`, and Cancel;
- Save is disabled in flight;
- immutable retry reuses UUID and payload;
- success uses `textContent` and shows CareerOps ID/open action;
- the open action accepts only the fixed local CareerOps UI origin and the
  server-provided Applications deep-link parameters;
- no request occurs before explicit Connect/Preview/Save action.

- [ ] **Step 2: Run the smoke test and verify failure**

Run:

```powershell
node test/sidepanel-smoke-test.js
```

Expected: FAIL because Side Panel files do not exist.

- [ ] **Step 3: Create the compact Side Panel UI**

Use familiar form controls with no nested decorative cards:

```text
CareerOps Capture
Connection state
Company
Role
Location
Application date
Status
Source
Notes
Duplicate result
[Refresh from page] [Preview]
[Cancel] [Save to CareerOps]
```

Keep form dimensions stable, labels readable, and errors adjacent to their
field. Use only `textContent`/`replaceChildren()` for dynamic content.

- [ ] **Step 4: Implement exact-target extraction**

Load `captureTarget`, call `chrome.tabs.get(target.tabId)`, and require
`tab.url === target.url`. Inject only `jobExtractor.js` into that Tab. Execute:

```javascript
globalThis.JobCaptureExtractor.extract(
  document,
  location.href,
  localCaptureDate
);
```

If permission is gone or URL changed, clear target and ask for a new Popup
click. Never query the current active Tab as fallback.

- [ ] **Step 5: Implement connection and pairing**

From the visible panel:

1. inspect LNA permission where supported;
2. on Connect, call anonymous health;
3. read token only in the trusted panel context;
4. call pair confirmation;
5. show permission, offline, timeout, and auth states separately.

Do not render token text.

- [ ] **Step 6: Implement preview and confirmed save**

Preview sends reviewed fields only. On duplicate response:

- `use_existing` includes selected `existing_application_id` and
  `edited_fields`;
- `create_anyway` includes that resolution;
- Cancel writes nothing.

After the first Save attempt, lock the payload and UUID. Retry uses the same
values. Editing requires `Capture another`, which clears the prior request and
starts a new explicit capture.

- [ ] **Step 7: Run Side Panel tests**

Run:

```powershell
node --check src/sidepanel.js
node test/sidepanel-smoke-test.js
```

Expected: PASS.

- [ ] **Step 8: Review and commit**

Suggested commit:

```powershell
git add src/sidepanel.html src/sidepanel.css src/sidepanel.js test/sidepanel-smoke-test.js
git commit -m "Add CareerOps capture review panel"
```

Do not push.

### Task 6: Documentation, Regression Checks, and Manual Synthetic Gate

**Files:**
- Modify: `README.md`
- Modify: `PRIVACY.md`
- Modify: `SECURITY.md`
- Modify: `docs/manual-test-checklist.md`
- Create: `test/job-capture-generic.html`
- Create: `test/job-capture-personio.html`
- Create: `test/job-capture-workday.html`

**Interfaces:**
- Documents pairing, explicit capture, permission recovery, duplicate choices,
  and the fixed local endpoint.

- [ ] **Step 1: Update privacy and security documentation**

State:

- token remains in trusted local extension storage;
- target session state contains only Tab ID, URL, and time;
- reviewed application fields go only to `127.0.0.1:8765`;
- no Gmail, cloud, telemetry, raw HTML, cookies, credentials, file uploads, or
  automatic application submission;
- the manifest permission covers any loopback port syntactically, while the
  production API client enforces port 8765.

- [ ] **Step 2: Add manual synthetic pages**

Create synthetic pages for generic metadata, JSON-LD, Personio-like markup, and
Workday-like markup. Use fake companies, roles, URLs, and dates only.

- [ ] **Step 3: Run all dependency-free automated checks**

Run:

```powershell
node --check src/storage.js
node --check src/options.js
node --check src/popup.js
node --check src/capture/jobExtractor.js
node --check src/capture/captureDraft.js
node --check src/capture/careerOpsClient.js
node --check src/sidepanel.js
node test/capture-storage-test.js
node test/job-capture-test.js
node test/careerops-client-test.js
node test/capture-target-test.js
node test/sidepanel-smoke-test.js
node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8')); console.log('manifest ok')"
git diff --check
git status --short
```

Expected: all checks pass and only planned Extension files are changed.

- [ ] **Step 4: Run manual Chrome 142 and current-Chrome verification**

Load the extension unpacked and verify:

- existing Autofill still works;
- file uploads remain manual;
- Popup remains the action entry point;
- Side Panel opens only from `Capture current job`;
- switching tabs after the click does not change the extraction target;
- LNA prompt can be triggered from the visible panel;
- denied LNA, Bridge offline, invalid token, and timeout are distinct;
- duplicate `use_existing` preserves unedited protected fields;
- repeated Save/retry creates one record;
- no hosted-demo or non-8765 request appears in DevTools Network;
- no real application is submitted or saved during the test.

- [ ] **Step 5: Capture synthetic-only evidence**

If screenshots are required, use only the synthetic pages and crop out browser
paths, tokens, real profile data, and real CareerOps records.

- [ ] **Step 6: Final scope review**

Confirm:

- no npm files or dependencies;
- no broad host permission;
- no content-script token access;
- no current-active-tab fallback;
- no Autofill regression;
- no real data in fixtures or screenshots;
- no commit was pushed.
