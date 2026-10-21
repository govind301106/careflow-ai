import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest, getCsrfToken } from "./api";
import { createCaseRequestGate, getCaseDetailsForSelection } from "./caseRequestGate";
import "./App.css";

const label = (value = "") => value.toLowerCase().replaceAll("_", " ");
const navIcons = { Overview: "⌂", "New intake": "+", Cases: "▣", Appointments: "◷", "Intake chat": "◌", "Case queue": "▤", "Clinician approvals": "✓" };

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cases, setCases] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [tab, setTab] = useState("Overview");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [registerMode, setRegisterMode] = useState(false);
  const [chatCase, setChatCase] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [clinicianRequests, setClinicianRequests] = useState([]);
  const [chatDraft, setChatDraft] = useState("");
  const [accountType, setAccountType] = useState("patient");
  const chatEndRef = useRef(null);
  const caseRequestGate = useRef(createCaseRequestGate());
  useEffect(() => { chatEndRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [chatMessages]);
  useEffect(() => { if (tab === "Clinician approvals") loadClinicianRequests(); }, [tab]);

  const refresh = useCallback(async (role = user?.role) => {
    if (!role) return;
    const [caseData, appointmentData] = await Promise.all([
      apiRequest("/cases/"), apiRequest("/appointments/"),
    ]);
    const caseItems = Array.isArray(caseData) ? caseData : caseData.results || [];
    setCases(caseItems);
    setAppointments(Array.isArray(appointmentData) ? appointmentData : appointmentData.results || []);
    return caseItems;
  }, [user?.role]);

  useEffect(() => {
    apiRequest("/auth/me/")
      .then(async (data) => {
        if (data.authenticated) {
          setUser(data);
          if (data.role === "patient" || data.role === "clinician") await refresh(data.role);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [refresh]);

  async function signIn(event) {
    event.preventDefault(); setError(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      await getCsrfToken();
      const data = await apiRequest("/auth/login/", { method: "POST", body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
      setUser(data); if (data.role === "patient" || data.role === "clinician") await refresh(data.role);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function register(event) {
    event.preventDefault(); setError(""); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await getCsrfToken();
      const account = await apiRequest("/auth/register/", { method: "POST", body: JSON.stringify({ account_type: accountType, full_name: data.get("full_name"), username: data.get("username"), email: data.get("email"), password: data.get("password"), password_confirmation: data.get("password_confirmation") }) });
      setUser(account); if (account.role === "patient") await refresh("patient");
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function startChat(item) {
    setChatCase(item); setTab("Intake chat"); setSelected(null); setBusy(true);
    try { const history = await apiRequest(`/cases/${item.id}/chat/`); if (history.length) { setChatMessages(history); } else { const response = await apiRequest(`/cases/${item.id}/chat/`, { method: "POST", body: JSON.stringify({ start: true }) }); setChatMessages([{ role: "assistant", content: response.message, mode: response.mode }]); } }
    catch (e) { setNotice(e.message); } finally { setBusy(false); }
  }

  async function sendChat(event) {
    event.preventDefault(); if (!chatDraft.trim() || !chatCase) return;
    const message = chatDraft.trim(); setChatDraft(""); setBusy(true);
    setChatMessages((items) => [...items, { role: "patient", content: message }]);
    try { const response = await apiRequest(`/cases/${chatCase.id}/chat/`, { method: "POST", body: JSON.stringify({ message }) }); setChatMessages((items) => [...items, { role: "assistant", content: response.message, mode: response.mode }]); }
    catch (e) { setNotice(e.message); } finally { setBusy(false); }
  }

  async function confirmChat() {
    if (!chatCase) return;
    setBusy(true);
    try { await apiRequest(`/cases/${chatCase.id}/chat/`, { method: "POST", body: JSON.stringify({ confirm: true, intake: {} }) }); await refresh(); setNotice("Your confirmed intake is saved on the case."); setTab("Cases"); setChatCase(null); }
    catch (e) { setNotice(e.message); } finally { setBusy(false); }
  }

  async function signOut() {
    try { await apiRequest("/auth/logout/", { method: "POST", body: "{}" }); }
    finally { setUser(null); setCases([]); setAppointments([]); setSelected(null); setDetail(null); }
  }

  async function loadClinicianRequests() {
    try { setClinicianRequests(await apiRequest("/admin/clinician-requests/")); }
    catch (e) { setNotice(e.message); }
  }
  async function reviewClinician(id, decision) {
    setBusy(true);
    try { await apiRequest(`/admin/clinician-requests/${id}/review/`, { method: "POST", body: JSON.stringify({ decision }) }); await loadClinicianRequests(); setNotice(`Clinician request ${decision}d.`); }
    catch (e) { setNotice(e.message); } finally { setBusy(false); }
  }

  async function submitIntake(event) {
    event.preventDefault(); setNotice(""); setError(""); setBusy(true);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const symptoms = String(form.get("symptoms") || "").trim();
    if (!form.get("consent")) { setNotice("Consent is required before submitting an intake."); setBusy(false); return; }
    try {
      const item = await apiRequest("/cases/", { method: "POST", body: JSON.stringify({ patient_name: String(form.get("patient_name") || "").trim(), description: symptoms, preferred_language: "en" }) });
      await apiRequest(`/cases/${item.id}/consent/`, { method: "POST", body: JSON.stringify({ granted: true, purpose: "CareFlow case processing and clinician review", notice_version: "1.0" }) });
      await apiRequest(`/cases/${item.id}/intake/`, { method: "PUT", body: JSON.stringify({ symptoms: symptoms.split(/\s*,\s*/).filter(Boolean), duration: form.get("duration"), severity_description: form.get("severity"), medical_history: form.get("medical_history"), current_medications: form.get("current_medications"), allergies: form.get("allergies"), additional_information: form.get("additional_information"), original_answers: { symptoms, duration: form.get("duration"), severity: form.get("severity") } }) });
      const file = form.get("report");
      if (file?.size) {
        const body = new FormData(); body.append("file", file);
        await apiRequest(`/cases/${item.id}/attachments/`, { method: "POST", body });
      }
      await refresh(); setNotice("Intake saved. You can now clarify missing information in the deterministic intake chat."); formElement.reset(); await startChat(item);
    } catch (e) { setNotice(`Submission could not be completed: ${e.message} Your case may have been created; refresh cases before retrying.`); }
    finally { setBusy(false); }
  }

  async function openCase(item) {
    const requestId = caseRequestGate.current.begin();
    setSelected(item); setDetail(null); setNotice("");
    try {
      const [intake, attachments, consent, activities, aiResults, clinicianReviews, patientAI] = await Promise.all([
        apiRequest(`/cases/${item.id}/intake/`).catch((error) => error.message === "No intake submitted yet." ? null : ({ unavailable: true, unavailableReason: error.message })),
        apiRequest(`/attachments/`).then((data) => (Array.isArray(data) ? data : data.results || []).filter((a) => a.case === item.id)),
        user.role === "patient" ? apiRequest(`/cases/${item.id}/consent/`).catch(() => []) : Promise.resolve([]),
        user.role === "clinician" ? apiRequest(`/cases/${item.id}/activities/`).catch(() => []) : Promise.resolve([]),
        user.role === "clinician" ? apiRequest(`/cases/${item.id}/ai_results/`).catch(() => []) : Promise.resolve([]),
        user.role === "clinician" ? apiRequest(`/cases/${item.id}/reviews/`).catch(() => []) : Promise.resolve([]),
        user.role === "patient" ? apiRequest(`/cases/${item.id}/patient-ai-suggestions/`).catch((e) => ({ status: "error", detail: e.message })) : Promise.resolve(null),
      ]);
      const patientReview = user.role === "patient"
        ? await apiRequest(`/cases/${item.id}/patient-review/`).catch(() => ({ status: "error" }))
        : null;
      if (!caseRequestGate.current.isCurrent(requestId)) return;
      setDetail({ caseId: item.id, intake, attachments, consent, activities, aiResults, clinicianReviews, patientReview, patientAI });
    } catch (e) {
      if (caseRequestGate.current.isCurrent(requestId)) setNotice(e.message);
    }
  }

  async function retryPatientReview() {
    if (!selected) return;
    const requestId = caseRequestGate.current.begin();
    const caseId = selected.id;
    setDetail((current) => ({ ...current, patientReview: { status: "loading" } }));
    try {
      const patientReview = await apiRequest(`/cases/${caseId}/patient-review/`);
      if (caseRequestGate.current.isCurrent(requestId)) setDetail((current) => ({ ...current, caseId, patientReview }));
    } catch {
      if (caseRequestGate.current.isCurrent(requestId)) setDetail((current) => ({ ...current, caseId, patientReview: { status: "error" } }));
    }
  }

  async function act(path, method, body = {}) {
    setBusy(true); setNotice("");
    try { await apiRequest(path, { method, body: JSON.stringify(body) }); const freshCases = await refresh(); if (selected) { const fresh = freshCases.find((item) => item.id === selected.id) || selected; setSelected(fresh); await openCase(fresh); } setNotice("Changes saved."); }
    catch (e) { setNotice(e.message); } finally { setBusy(false); }
  }

  async function download(attachment) {
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api"}/attachments/${attachment.id}/download/`, { credentials: "include" });
      if (!response.ok) throw new Error("Download is unavailable or unauthorized.");
      const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement("a"); anchor.href = url; anchor.download = attachment.original_filename; anchor.click(); URL.revokeObjectURL(url);
    } catch (e) { setNotice(e.message); }
  }

  if (loading) return <main className="page-content">Loading CareFlow…</main>;
  if (!user) return <main className="auth-page"><section className="form-panel auth-panel"><div className="brand-mark">✚</div><div className="eyebrow">CAREFLOW AI</div><h1>{registerMode ? `Create a ${accountType} account` : "Welcome back"}</h1><p className="form-intro">{registerMode ? "Secure access to your care workspace." : "Sign in to continue to your care workspace."}</p>{error && <div className="inline-notice" role="alert">{error}</div>}<form onSubmit={registerMode ? register : signIn}>{registerMode && <><div className="account-toggle" role="group" aria-label="Account type"><button type="button" className={accountType === "patient" ? "selected" : ""} onClick={() => setAccountType("patient")}>Patient</button><button type="button" className={accountType === "clinician" ? "selected" : ""} onClick={() => setAccountType("clinician")}>Clinician</button></div>{accountType === "clinician" && <p className="inline-notice">Clinician access starts after administrator approval.</p>}<label>Full name<input name="full_name" required autoComplete="name" /></label><label>Email<input name="email" type="email" required autoComplete="email" /></label></>}<label>Username<input name="username" required autoComplete="username" /></label><label>Password<input name="password" type="password" required autoComplete={registerMode ? "new-password" : "current-password"} /></label>{registerMode && <label>Confirm password<input name="password_confirmation" type="password" required autoComplete="new-password" /></label>}<button className="primary-btn" disabled={busy}>{busy ? "Please wait…" : registerMode ? `Submit ${accountType} registration` : "Sign in"}</button></form><button className="text-btn auth-switch" onClick={() => { setRegisterMode(!registerMode); setError(""); }}>{registerMode ? "Already registered? Sign in" : "Create an account"}</button></section></main>;
  if (user.role === "pending_clinician") return <main className="auth-page"><section className="form-panel auth-panel"><div className="brand-mark">✓</div><div className="eyebrow">REGISTRATION RECEIVED</div><Badge value={user.approval_status?.toUpperCase() || "PENDING_APPROVAL"} /><h1>Pending administrator approval</h1><p className="form-intro">Your clinician request is in the review queue. Clinician tools and patient records remain unavailable until an administrator approves the account.</p><p className="profile-email">{user.email}</p><button className="primary-btn" onClick={signOut}>Sign out</button></section></main>;

  const clinician = user.role === "clinician";
  const selectedDetail = getCaseDetailsForSelection(detail, selected?.id);
  const activeConsent = selectedDetail?.consent?.find((record) => record.granted && !record.withdrawn_at);
  const tabs = user.is_staff ? ["Clinician approvals"] : clinician ? ["Case queue", "Appointments"] : ["Overview", "New intake", "Cases", "Appointments", "Intake chat"];
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#home" onClick={() => setTab(tabs[0])}><span className="brand-icon">✚</span><span>careflow<span className="brand-ai"> AI</span></span></a><div className="nav-label">{clinician ? "CLINICIAN WORKSPACE" : user.is_staff ? "ADMIN WORKSPACE" : "PATIENT PORTAL"}</div>{tabs.map((name) => <button key={name} className={`nav-item ${tab === name ? "active" : ""}`} onClick={() => { setTab(name); setSelected(null); setDetail(null); }}><span aria-hidden="true">{navIcons[name]}</span>{name}</button>)}<div className="sidebar-bottom"><div className="privacy-card"><strong>Human-led care</strong><p>AI output is advisory. Clinicians make final care decisions.</p></div><div className="profile"><div className="avatar">{(user.full_name || user.username).split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase()}</div><div className="profile-copy"><strong>{user.full_name || user.username}</strong><small>{user.email || user.username}</small><small>{user.role}</small></div><button className="text-btn signout-btn" onClick={signOut}>↪ Sign out</button></div></div></aside>
    <main className="main-content"><header className="topbar"><div className="breadcrumb">CareFlow <span>/</span> {tab}</div><span className="secure-label">Signed in as {user.username}</span></header><div className="page-content">{error && <div className="inline-notice">{error}</div>}{notice && <div className="inline-notice">{notice}</div>}
      {tab === "Overview" && <><section className="welcome"><div><div className="eyebrow">YOUR HEALTH WORKSPACE</div><h1>Healthcare, with you at the center.</h1><p>Share symptoms and reports for clinician review.</p><button className="primary-btn" onClick={() => setTab("New intake")}>Start symptom intake</button></div></section><div className="section-heading"><h2>Your care at a glance</h2></div><section className="stats-grid"><Stat label="Total cases" value={cases.length} /><Stat label="Awaiting review" value={cases.filter((item) => item.status === "NEEDS_REVIEW").length} /><Stat label="Appointments" value={appointments.length} /></section><CaseList items={cases.slice(0, 3)} onOpen={openCase} /></>}
      {tab === "New intake" && <section className="form-panel"><div className="eyebrow">PATIENT INTAKE</div><h1>Tell us how you’re feeling.</h1><p className="form-intro">Submitted information and reports are shared with your care team after consent.</p><form onSubmit={submitIntake}><label>Patient name<input name="patient_name" required defaultValue={user.username} /></label><label>Symptoms<textarea name="symptoms" required rows={4} placeholder="Describe your symptoms" /></label><div className="two-columns"><label>Duration<select name="duration"><option>Less than a day</option><option>1–2 days</option><option>3–7 days</option><option>More than a week</option></select></label><label>Severity<select name="severity"><option>Mild</option><option>Moderate</option><option>Severe</option></select></label></div><label>Medical history<textarea name="medical_history" rows={2} /></label><label>Current medications<textarea name="current_medications" rows={2} /></label><label>Allergies<textarea name="allergies" rows={2} /></label><label>Additional information<textarea name="additional_information" rows={2} /></label><label className="upload-area"><strong>Attach a medical report (optional)</strong><small>PDF, JPEG or PNG, maximum 10 MB. Stored privately.</small><input name="report" type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" /></label><label className="consent-row"><input type="checkbox" name="consent" required /><span>I consent to CareFlow storing this information and sharing it with an assigned clinician for case review. I can withdraw consent later.</span></label><button className="primary-btn" disabled={busy}>{busy ? "Submitting…" : "Submit intake"}</button></form></section>}
      {(tab === "Cases" || tab === "Case queue") && <section className="panel full-panel"><div className="panel-heading"><div><h1>{clinician ? "Case queue" : "Your cases"}</h1><p>{clinician ? "Unassigned cases and cases assigned to you." : "Open a case to review its details."}</p></div>{!clinician && <button className="primary-btn" onClick={() => setTab("New intake")}>New intake</button>}</div><CaseList items={cases} onOpen={openCase} /></section>}
      {tab === "Clinician approvals" && user.is_staff && <section className="panel full-panel"><div className="panel-heading"><div><h1>Clinician requests</h1><p>Review access requests before granting clinician permissions.</p></div><button className="text-btn" onClick={loadClinicianRequests}>Refresh</button></div>{clinicianRequests.length ? clinicianRequests.map((request) => <article className="approval-row" key={request.id}><div><strong>{request.full_name || request.username}</strong><p>{request.email} · Requested {new Date(request.created_at).toLocaleDateString()}</p></div><div className="approval-actions"><button className="primary-btn" disabled={busy} onClick={() => reviewClinician(request.id, "approve")}>Approve</button><button className="secondary-btn" disabled={busy} onClick={() => reviewClinician(request.id, "reject")}>Reject</button></div></article>) : <p className="empty-state">No pending clinician requests.</p>}</section>}
      {tab === "Intake chat" && <section className="panel full-panel"><h1>Intake chat</h1><p className="form-intro">Rule-based intake assistant. It gathers your responses and does not diagnose or provide emergency detection.</p>{chatCase ? <><div className="chat-transcript" aria-live="polite" aria-label="Intake conversation">{chatMessages.map((m, i) => <div key={i} className={`chat-message ${m.role === "patient" ? "patient-message" : "assistant-message"}`}><span>{m.role === "assistant" ? "CareFlow" : "You"}</span><p>{m.content}</p></div>)}<div ref={chatEndRef} /></div><form className="chat-composer" onSubmit={sendChat}><label htmlFor="chat-message">Your response</label><div className="chat-compose-row"><textarea id="chat-message" value={chatDraft} onChange={(e) => setChatDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (chatDraft.trim() && !busy) sendChat(e); } }} placeholder="Type your response…" rows={3} disabled={busy} /><button className="primary-btn" disabled={busy || !chatDraft.trim()}>{busy ? "Sending…" : "Send"}</button></div><small>Enter to send · Shift+Enter for a new line</small></form><p className="notice-banner">For urgent symptoms, contact local emergency services. This assistant does not diagnose.</p><button className="primary-btn" onClick={confirmChat} disabled={busy}>Review and confirm intake</button></> : <><p>Start a chat from a submitted case to clarify missing details.</p><CaseList items={cases} onOpen={startChat} /></>}</section>}
      {selected && !selectedDetail && <section className="panel case-detail-loading" role="status">Loading case details…</section>}
      {selected && selectedDetail && <div className="case-detail-stack">
        <section className="panel case-detail-header">
          <div className="case-detail-title"><div className="eyebrow">CASE CF-{selected.id}</div><h1>{selected.patient_name}</h1><p>{selected.description || "No original patient description was saved."}</p></div>
          <div className="case-detail-controls"><div className="case-state-badges"><Badge value={selected.status} /><Badge value={selected.priority} kind="priority" /></div>{clinician && <><span className="assignment-label">{selected.assigned_clinician ? (selected.assigned_clinician === user.id ? "Assigned to you" : `Assigned clinician #${selected.assigned_clinician}`) : "Unassigned"}</span>{!selected.assigned_clinician && <button className="secondary-btn" disabled={busy} onClick={() => act(`/cases/${selected.id}/assign/`, "PATCH", { clinician_id: user.id })}>Assign to me</button>}</>}{!clinician && <div className="consent-control"><Badge value={activeConsent ? "CONSENT_GRANTED" : selectedDetail.consent?.some((record) => record.withdrawn_at) ? "CONSENT_WITHDRAWN" : "CONSENT_NOT_RECORDED"} />{activeConsent && <button className="text-btn" onClick={() => act(`/consents/${activeConsent.id}/withdraw/`, "POST")}>Withdraw consent</button>}</div>}<button className="text-btn close-case" onClick={() => { setSelected(null); setDetail(null); }}>Close</button></div>
          {clinician && selected.assigned_clinician === user.id && <label className="compact-status-control">Case workflow status<select aria-label="Update case status" value={selected.status} onChange={(e) => act(`/cases/${selected.id}/update_status/`, "PATCH", { status: e.target.value })}>{["NEEDS_REVIEW", "IN_REVIEW", "NEEDS_INFORMATION", "ESCALATED", "APPROVED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></label>}
        </section>
        <CaseIntakeSection intake={selectedDetail.intake} description={selected.description} clinician={clinician} />
        {clinician ? <AIResultsSection results={selectedDetail.aiResults} /> : <AIResultsSection patientAI={selectedDetail.patientAI} onRetry={() => openCase(selected)} />}
        {clinician ? <ClinicianReviewSection reviews={selectedDetail.clinicianReviews} caseStatus={selected.status} selected={selected} user={user} busy={busy} act={act} /> : <PatientReviewPanel review={selectedDetail.patientReview} onRetry={retryPatientReview} />}
        {clinician && <section className="panel detail-section activity-section"><div className="detail-section-heading"><div><h3>Case activity</h3><p>Recorded workflow events for this case.</p></div></div>{selectedDetail.activities?.length ? <ol className="activity-timeline">{[...selectedDetail.activities].sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp)).map((activity) => <li key={activity.id}><time dateTime={activity.timestamp}>{new Date(activity.timestamp).toLocaleString()}</time><strong>{label(activity.action)}</strong>{activity.old_status && <span>{label(activity.old_status)} → {label(activity.new_status)}</span>}</li>)}</ol> : <p className="detail-empty">No case activity has been recorded.</p>}</section>}
        {selectedDetail.attachments?.map((a) => <p className="attachment-row" key={a.id}>Private report: {a.original_filename} <button className="text-btn" onClick={() => download(a)}>Download</button></p>)}
      </div>}      {tab === "Appointments" && <AppointmentPanel appointments={appointments} clinician={clinician} refresh={refresh} />}
    </div></main></div>;
}

function Stat({ label: title, value }) { return <div className="stat-card"><div><p>{title}</p><strong>{value}</strong></div></div>; }
function CaseIntakeSection({ intake, description, clinician }) {
  const original = intake?.original_answers && typeof intake.original_answers === "object" ? Object.entries(intake.original_answers).filter(([key]) => key !== "chat_messages") : [];
  return <section className="panel detail-section intake-section"><div className="detail-section-heading"><div><h3>Patient intake</h3><p>Original patient information and structured intake, when available.</p></div></div>{intake?.unavailable ? <div className="intake-missing"><p className="detail-empty">{clinician && /assigned clinician/i.test(intake.unavailableReason || "") ? "Structured intake is available after this case is assigned to you." : "Structured intake could not be loaded."}</p><p><strong>Original patient-provided information</strong></p><p>{description || "No original patient description was saved."}</p></div> : intake ? <><div className="intake-grid"><p><strong>Symptoms</strong><span>{Array.isArray(intake.symptoms) ? intake.symptoms.join(", ") || "Not specified" : intake.symptoms || "Not specified"}</span></p><p><strong>Symptom onset</strong><span>{intake.symptom_onset || "Not provided"}</span></p><p><strong>Duration</strong><span>{intake.duration || "Not provided"}</span></p><p><strong>Severity</strong><span>{intake.severity_description || "Not provided"}</span></p><p><strong>Progression</strong><span>{intake.progression || "Not provided"}</span></p><p><strong>Medical history</strong><span>{intake.medical_history || "Not provided"}</span></p><p><strong>Medications</strong><span>{intake.current_medications || "Not provided"}</span></p><p><strong>Allergies</strong><span>{intake.allergies || "Not provided"}</span></p><p><strong>Additional information</strong><span>{intake.additional_information || "Not provided"}</span></p></div>{original.length > 0 && <details className="original-answers"><summary>Original responses</summary><dl>{original.map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd></div>)}</dl></details>}{clinician && intake.original_answers?.chat_messages?.length > 0 && <details className="original-answers"><summary>Patient chat source messages</summary><ol>{intake.original_answers.chat_messages.map((message, index) => <li key={index}>{message}</li>)}</ol></details>}</> : <div className="intake-missing"><p className="detail-empty">No structured intake was saved for this case.</p><p><strong>Original patient-provided information</strong></p><p>{description || "No original patient description was saved."}</p></div>}</section>;
}

const AI_DISPLAY_FIELDS = [
  ["patient_summary", "Patient summary"], ["missing_information", "Missing information"],
  ["unclear_information", "Unclear information"], ["contradictions", "Contradictions"],
  ["urgent_alerts", "Urgent alerts and supporting evidence"],
  ["suggested_follow_up_questions", "Suggested follow-up questions"],
  ["suggested_priority", "Suggested triage priority"], ["priority_explanation", "Priority explanation"],
  ["source_references", "Source references"],
];
function displayValue(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function AIResultsSection({ results = [], patientAI, onRetry }) {
  const patientResult = patientAI?.status === "completed" ? patientAI.result : null;
  const entries = patientResult ? AI_DISPLAY_FIELDS.filter(([key]) => Object.hasOwn(patientResult.suggestions || {}, key)).map(([key, title]) => [title, patientResult.suggestions[key]]) : [];
  return <section className="panel detail-section ai-analysis-section"><div className="detail-section-heading"><div><h3>AI Suggestions</h3><p>Advisory analysis only. It does not make or replace a clinician decision.</p></div><span className="workflow-label">{patientAI ? patientAI.status.replaceAll("_", " ") : results.length ? "saved results" : "not configured"}</span></div>{patientAI ? <>
    {patientAI.status === "not_configured" && <p className="detail-empty">AI analysis is not configured. Your clinician review can proceed independently.</p>}
    {patientAI.status === "not_started" && <p className="detail-empty">AI analysis is configured but has not been submitted for this case. Your clinician review can proceed independently.</p>}
    {patientAI.status === "in_progress" && <p className="detail-empty"><Badge value="PROCESSING" /> AI analysis is in progress. Suggestions will appear here when a validated result is saved.</p>}
    {patientAI.status === "failed" && <p className="detail-empty">AI analysis failed. No suggestions are available. This does not affect your clinician review.</p>}
    {patientAI.status === "unavailable" && <p className="detail-empty">A saved AI result has not passed patient-display validation, so its contents are unavailable.</p>}
    {patientAI.status === "error" && <p className="detail-empty" role="alert">AI suggestions could not be loaded. <button className="text-btn" type="button" onClick={onRetry}>Retry</button></p>}
    {patientResult && <><div className="ai-result-heading"><Badge value="COMPLETED" /><span>{patientResult.model_name || "Validated AI analysis"}{patientResult.schema_version ? ` · Schema ${patientResult.schema_version}` : ""}</span><time dateTime={patientResult.created_at}>{new Date(patientResult.created_at).toLocaleDateString()}</time></div>{entries.length ? <div className="suggestion-grid">{entries.map(([title, value]) => <article key={title}><h4>{title}</h4><p>{displayValue(value)}</p></article>)}</div> : <p className="detail-empty">A validated result is saved, but it does not include the patient-facing fields agreed for display.</p>}</>}
  </> : results.length ? results.map((result) => <article className="ai-result" key={result.id}><div className="ai-result-heading"><Badge value={result.status} /><span>{result.model_name || "AI analysis"}{result.schema_version ? ` · Schema ${result.schema_version}` : ""}</span><time dateTime={result.created_at}>{new Date(result.created_at).toLocaleDateString()}</time></div>{result.status === "COMPLETED" ? result.is_validated ? <><h4>Persisted structured suggestions</h4><pre>{JSON.stringify(result.structured_output, null, 2)}</pre>{result.uncertainty_flags?.length > 0 && <p><strong>Uncertainty flags:</strong> {displayValue(result.uncertainty_flags)}</p>}{result.rule_triggers?.length > 0 && <p><strong>Rule triggers:</strong> {displayValue(result.rule_triggers)}</p>}{result.evidence?.length > 0 && <p><strong>Evidence references:</strong> {displayValue(result.evidence)}</p>}</> : <p className="detail-empty">Saved output has not passed validation. Do not use it as a clinical suggestion.</p> : <p className="detail-empty">{result.status === "FAILED" ? "AI analysis failed. No suggestions are available." : "AI analysis is in progress. No suggestions are available yet."}</p>}</article>) : <p className="detail-empty">AI pipeline is not configured and no AI result has been saved. This state is independent of the case workflow status.</p>}</section>;
}

function ClinicianReviewSection({ reviews = [], caseStatus, selected, user, busy, act }) {
  const review = [...reviews].sort((left, right) => new Date(right.created_at) - new Date(left.created_at))[0];
  const canReview = selected.status !== "APPROVED" && selected.assigned_clinician === user.id;
  return <section className="panel detail-section clinician-review-section"><div className="detail-section-heading"><div><h3>Clinical review</h3><p>Clinician-authored decision, separate from AI suggestions.</p></div><Badge value={review?.is_finalized ? review.decision : (review?.decision === "IN_REVIEW" || caseStatus === "IN_REVIEW" ? "IN_REVIEW" : "NEEDS_REVIEW")} /></div>{!review ? <p className="detail-empty">{caseStatus === "IN_REVIEW" ? "Case workflow is in review; no review record has been saved yet." : "No clinician review has been saved for this case."}</p> : <><p className="review-saved-state">{review.is_finalized ? "Finalized clinician decision" : "Draft review in progress"}</p>{review.is_finalized && <p><strong>Decision:</strong> {label(review.decision)}</p>}{review.patient_comments && <p><strong>Patient-facing comments:</strong> {review.patient_comments}</p>}{review.reviewer_comments && <p><strong>Internal clinician notes:</strong> {review.reviewer_comments}</p>}{review.edited_note && <p><strong>Clinician working note:</strong> {review.edited_note}</p>}{review.follow_up_instructions && <p><strong>Follow-up instructions:</strong> {review.follow_up_instructions}</p>}{review.referral_details && <p><strong>Referral details:</strong> {review.referral_details}</p>}<small className="review-date">Saved {new Date(review.created_at).toLocaleString()}</small></>}{selected.status === "APPROVED" && <p className="detail-empty">This case is approved and cannot be reviewed again.</p>}{!canReview && selected.status !== "APPROVED" && <p className="detail-empty">Assign this case to yourself before saving a clinician review.</p>}{canReview && <form className="clinician-review-form" onSubmit={(e) => { e.preventDefault(); const data = new FormData(e.currentTarget); act(`/cases/${selected.id}/add_review/`, "POST", { decision: data.get("decision"), reviewer_comments: data.get("comments"), patient_comments: data.get("patient_comments"), follow_up_instructions: data.get("follow_up"), referral_details: data.get("referral") }); }}><label>Review decision<select name="decision" defaultValue={review?.is_finalized ? "IN_REVIEW" : review?.decision || "IN_REVIEW"}><option value="IN_REVIEW">Draft / in progress</option><option value="NEEDS_INFORMATION">Needs information</option><option value="ESCALATED">Escalated</option><option value="APPROVED">Approved</option></select></label><label>Internal clinician notes<textarea name="comments" rows={2} defaultValue={review?.reviewer_comments || ""} /></label><label>Comments for patient<textarea name="patient_comments" rows={2} defaultValue={review?.is_finalized ? "" : review?.patient_comments || ""} /></label><div className="two-columns"><label>Follow-up instructions<textarea name="follow_up" rows={2} defaultValue={review?.follow_up_instructions || ""} /></label><label>Referral details<textarea name="referral" rows={2} defaultValue={review?.referral_details || ""} /></label></div><button className="primary-btn" disabled={busy}>Save review</button></form>}</section>;
}
function PatientReviewPanel({ review, onRetry }) {
  const saved = review?.status === "completed" ? review.review : null;
  const status = saved ? saved.decision : review?.status === "in_review" ? "IN_REVIEW" : review?.status === "error" || review?.status === "loading" ? "UNKNOWN" : "NEEDS_REVIEW";
  return <section className="panel detail-section patient-review-section" aria-live="polite">
    <div className="detail-section-heading"><div><h3>Clinical Review</h3><p>Finalized clinician decision and patient-visible instructions.</p></div><Badge value={status} /></div>
    {review?.status === "pending" && <p className="detail-empty" role="status">Awaiting clinician review.</p>}
    {review?.status === "in_review" && <p className="detail-empty" role="status">In review. The clinician has not finalized a decision.</p>}
    {review?.status === "loading" && <p className="detail-empty" role="status">Checking clinical review status…</p>}
    {(review?.status === "error" || !review) && <div className="review-error" role="alert"><p>Clinical review status is temporarily unavailable.</p><button className="text-btn" type="button" onClick={onRetry}>Retry</button></div>}
    {saved && <><p className="review-saved-state"><strong>Final clinician decision:</strong> {label(saved.decision)}</p>{saved.patient_comments && <p><strong>Clinician comments</strong><span>{saved.patient_comments}</span></p>}{saved.follow_up_instructions && <p><strong>Follow-up instructions</strong><span>{saved.follow_up_instructions}</span></p>}{saved.referral_details && <p><strong>Referral details</strong><span>{saved.referral_details}</span></p>}{saved.created_at && <small className="review-date">Reviewed {new Date(saved.created_at).toLocaleDateString()}</small>}</>}
  </section>;
}
function Badge({ value, kind = "status" }) {
  const normalized = String(value || "UNKNOWN").toUpperCase();
  const alert = ["RED", "ESCALATED"].includes(normalized);
  const good = ["APPROVED", "CONSENT_GRANTED", "GRANTED"].includes(normalized);
  const pending = ["NEEDS_REVIEW", "NEEDS_INFORMATION", "PENDING", "PENDING_APPROVAL", "REQUESTED", "YELLOW"].includes(normalized);
  const progress = ["PROCESSING", "IN_REVIEW", "CONFIRMED"].includes(normalized);
  const rejected = ["REJECTED", "FAILED", "CANCELLED"].includes(normalized);
  const tone = kind === "priority" ? (normalized === "RED" ? "urgent" : normalized === "YELLOW" ? "pending" : "neutral") : alert ? "urgent" : good ? "approved" : pending ? "pending" : progress ? "progress" : rejected ? "rejected" : "neutral";
  const icon = kind === "priority" ? (normalized === "RED" ? "⚠" : normalized === "YELLOW" ? "◷" : "•") : alert ? "⚠" : good ? "✓" : pending ? "◷" : progress ? "↻" : rejected ? "!" : "•";
  return <span className={`status-badge ${tone} ${kind}`}><span aria-hidden="true">{icon}</span>{kind === "priority" ? priorityLabel(normalized) : label(normalized)}</span>;
}

function priorityLabel(value) {
  return ({ RED: "Immediate review", YELLOW: "Prompt review", GREEN: "No configured warning trigger", UNASSESSED: "Unassessed" })[value] || "Unknown";
}

function CaseList({ items, onOpen }) { return <div className="case-list">{items.length ? items.map((item) => <button className="case-row" key={item.id} onClick={() => onOpen(item)}><span className="case-info"><strong>{item.patient_name}</strong><small>CF-{item.id} · {new Date(item.created_at).toLocaleDateString()}</small></span><span className="case-badges"><Badge value={item.status} /><Badge value={item.priority} kind="priority" /></span><span className="case-open">Open case <span aria-hidden="true">→</span></span></button>) : <p className="empty-state">No cases available.</p>}</div>; }
function AppointmentPanel({ appointments, clinician, refresh }) {
  const [message, setMessage] = useState("");
  async function submit(e) { e.preventDefault(); const form = e.currentTarget; const data = new FormData(form); try { await apiRequest("/appointments/", { method: "POST", body: JSON.stringify({ scheduled_at: new Date(data.get("scheduled_at")).toISOString(), reason: data.get("reason") }) }); await refresh(); setMessage("Appointment request submitted."); form.reset(); } catch (err) { setMessage(err.message); } }
  async function update(id, status) { try { await apiRequest(`/appointments/${id}/`, { method: "PATCH", body: JSON.stringify({ status }) }); await refresh(); } catch (err) { setMessage(err.message); } }
  return <section className="panel full-panel"><h1>Appointments</h1>{message && <div className="inline-notice">{message}</div>}{!clinician && <form onSubmit={submit}><label>Requested date and time<input name="scheduled_at" type="datetime-local" required /></label><label>Reason<textarea name="reason" rows={2} /></label><button className="primary-btn">Request appointment</button></form>}{appointments.map((item) => <div className="case-row" key={item.id}><div className="case-info"><strong>{new Date(item.scheduled_at).toLocaleString()}</strong><small>{item.reason || "No reason provided"} · {label(item.status)}</small></div>{clinician && <select aria-label="Appointment status" value={item.status} onChange={(e) => update(item.id, e.target.value)}>{["REQUESTED", "CONFIRMED", "CANCELLED", "COMPLETED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select>}</div>)}</section>;
}

export default App;
