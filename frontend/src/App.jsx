
import { useEffect, useState } from "react";
import { apiRequest } from "./api";
import "./App.css";



function App() {
  const [activeTab, setActiveTab] = useState("Overview");
  const [cases, setCases] = useState([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [apiError, setApiError] = useState("");

  useEffect(() => {
    apiRequest("/cases/")
      .then((data) => {
        const items = Array.isArray(data) ? data : data.results || [];

        setCases(
          items.map((item) => ({
            id: `CF-${item.id}`,
            title: item.description,
            date: new Date(item.created_at).toLocaleDateString(),
            status: item.status.replaceAll("_", " "),
            priority: item.priority,
          }))
        );
      })
      .catch((error) => setApiError(error.message))
      .finally(() => setLoadingCases(false));
  }, []);
  const [patientName, setPatientName] = useState("");
  const [symptoms, setSymptoms] = useState("");
  const [duration, setDuration] = useState("1–2 days");
  const [severity, setSeverity] = useState("Moderate");
  const [notice, setNotice] = useState("");
  const [consent, setConsent] = useState(false);
  const [report, setReport] = useState(null);


  async function submitIntake(event) {
    event.preventDefault();
    setNotice("");

    if (!consent) {
      setNotice("Please provide consent before submitting.");
      return;
    }

    if (!patientName.trim() || !symptoms.trim()) {
      setNotice("Please enter your name and describe your symptoms.");
      return;
    }

    try {
      const newCase = await apiRequest("/cases/", {
        method: "POST",
        body: JSON.stringify({
          patient_name: patientName.trim(),
          description: symptoms.trim(),
          preferred_language: "en",
        }),
      });

      await apiRequest(`/cases/${newCase.id}/consent/`, {
        method: "POST",
        body: JSON.stringify({
          granted: true,
          purpose: "CareFlow case processing",
          notice_version: "1.0",
        }),
      });

      await apiRequest(`/cases/${newCase.id}/intake/`, {
        method: "PUT",
        body: JSON.stringify({
          symptoms: symptoms.trim().split(/\s*,\s*/),
          duration,
          severity_description: severity,
          original_answers: {
            symptoms: symptoms.trim(),
            duration,
            severity,
          },
        }),
      });

      const updatedCases = await apiRequest("/cases/");
      const items = Array.isArray(updatedCases)
        ? updatedCases
        : updatedCases.results || [];

      setCases(
        items.map((item) => ({
          id: `CF-${item.id}`,
          title: item.description,
          date: new Date(item.created_at).toLocaleDateString(),
          status: item.status.replaceAll("_", " "),
          priority: item.priority,
        }))
      );

      setNotice("Your intake was submitted successfully.");
      setSymptoms("");
      setPatientName("");
      setReport(null);
      setConsent(false);
      setActiveTab("Cases");
    } catch (error) {
      setNotice(`Submission failed: ${error.message}`);
    }
  }


  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setActiveTab("Overview")}>
          <span className="brand-icon">✳</span>
          <span>careflow<span className="brand-ai"> AI</span></span>
        </a>

        <div className="nav-label">PATIENT PORTAL</div>

        {[
          ["Overview", "⌂"],
          ["New intake", "＋"],
          ["Cases", "▤"],
          ["Appointments", "▦"],
        ].map(([label, icon]) => (
          <button
            key={label}
            className={`nav-item ${activeTab === label ? "active" : ""}`}
            onClick={() => setActiveTab(label)}
          >
            <span>{icon}</span>
            {label}
          </button>
        ))}

        <div className="sidebar-bottom">
          <div className="privacy-card">
            <span className="privacy-icon">♧</span>
            <strong>Your health, your control</strong>
            <p>Your information should be handled privately and securely.</p>
          </div>
          <div className="profile">
            <div className="avatar">P</div>
            <div>
              <strong>Patient portal</strong>
              <small>Demo account</small>
            </div>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">CareFlow <span>/</span> {activeTab}</div>
          <div className="topbar-right">
            <span className="secure-label"><span /> Secure care workspace</span>
            <div className="avatar small">P</div>
          </div>
        </header>

        <div className="page-content">
          {activeTab === "Overview" && (
            <>
              <section className="welcome">
                <div>
                  <div className="eyebrow">YOUR HEALTH WORKSPACE</div>
                  <h1>Healthcare, with you at the center.</h1>
                  <p>Share your symptoms, organize your reports, and prepare for clinician review.</p>
                  <button className="primary-btn" onClick={() => setActiveTab("New intake")}>
                    <span>＋</span> Start symptom intake
                  </button>
                </div>
                <div className="welcome-art" aria-hidden="true">
                  <div className="art-circle circle-one" />
                  <div className="art-circle circle-two" />
                  <div className="medical-cross">✚</div>
                  <div className="art-card">Care that listens.</div>
                </div>
              </section>

              <div className="section-heading">
                <div>
                  <h2>Your care at a glance</h2>
                  <p>A simple overview of your submitted information.</p>
                </div>
              </div>

              <section className="stats-grid">
                <StatCard label="Total cases" value={cases.length} icon="▤" />
                <StatCard label="Awaiting review" value={cases.filter((item) => item.status === "Needs review").length} icon="◷" />
                <StatCard label="Appointments" value="—" icon="▦" />
              </section>

              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent cases</h2>
                    <p>Follow the progress of your submitted symptoms.</p>
                  </div>
                  <button className="text-btn" onClick={() => setActiveTab("Cases")}>View all →</button>
                </div>
                <CaseList cases={cases.slice(0, 3)} />
              </section>

              <div className="notice-banner">
                <span className="notice-symbol">i</span>
                <p><strong>CareFlow supports clinician review.</strong> This demo does not provide a diagnosis or replace professional medical advice.</p>
              </div>
            </>
          )}

          {activeTab === "New intake" && (
            <section className="form-panel">
              <div className="eyebrow">PATIENT INTAKE</div>
              <h1>Tell us how you're feeling.</h1>
              <p className="form-intro">
                Share your symptoms and relevant details for clinician review.
              </p>

              {notice && <div className="inline-notice">{notice}</div>}

              <form onSubmit={submitIntake}>
                <label>
                  Patient name 
                  <input value={patientName} onChange={(event) => setPatientName(event.target.value)} placeholder="Enter your name" />
                </label>

                <label>
                  What symptoms are you experiencing?
                  <textarea required value={symptoms} onChange={(event) => setSymptoms(event.target.value)} placeholder="Describe your symptoms, when they started, and anything that makes them better or worse." rows={5} />
                </label>

                <div className="two-columns">
                  <label>
                    How long have you had them?
                    <select value={duration} onChange={(event) => setDuration(event.target.value)}>
                      <option>Less than a day</option>
                      <option>1–2 days</option>
                      <option>3–7 days</option>
                      <option>More than a week</option>
                    </select>
                  </label>
                  <label>
                    How severe do they feel?
                    <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
                      <option>Mild</option>
                      <option>Moderate</option>
                      <option>Severe</option>
                    </select>
                  </label>
                </div>

                <label className="upload-area">
                  <span className="upload-icon">↑</span>
                  <strong>{report ? report.name : "Attach a previous medical report"}</strong>
                  <small>PDF, JPG or PNG · Demo only; files are not uploaded to Django</small>
                  <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(event) => setReport(event.target.files?.[0] || null)} />
                </label>

                <label className="consent-row">
                  <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                  <span>
                    I consent to CareFlow recording and processing this information for case review.
                  </span>
                </label>

                <button className="primary-btn submit-btn" type="submit">Submit intake →</button>
              </form>
            </section>
          )}

          {activeTab === "Cases" && (
            <section className="panel full-panel">
              <div className="panel-heading">
                <div><h1>Your cases</h1><p>Submitted symptom intakes and their current status.</p></div>
                <button className="primary-btn" onClick={() => { setNotice(""); setActiveTab("New intake"); }}>＋ New intake</button>
              </div>
              <CaseList cases={cases} />
            </section>
          )}

          {activeTab === "Appointments" && (
            <section className="panel full-panel">
              <h1>Appointments</h1>
              <p>Appointment booking will be connected to the Django API in a later step.</p>
              <div className="empty-state"><span>▦</span><h3>No appointments connected</h3><p>This demo doesn't retrieve real appointment records yet.</p></div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

function StatCard({ label, value, icon }) {
  return (
    <div className="stat-card">
      <span className="stat-icon">{icon}</span>
      <div><p>{label}</p><strong>{value}</strong></div>
    </div>
  );
}

function CaseList({ cases }) {
  if (!cases.length) {
    return <div className="empty-state"><span>▤</span><h3>No cases yet</h3><p>Your submitted intakes will appear here.</p></div>;
  }

  return (
    <div className="case-list">
      {cases.map((item) => (
        <div className="case-row" key={item.id}>
          <div className="case-symbol">✚</div>
          <div className="case-info"><strong>{item.title}</strong><small>{item.id} · {item.date}</small></div>
          <span className="status-pill">{item.status}</span>
          <span className="priority-label">{item.priority}</span>
        </div>
      ))}
    </div>
  );
}

export default App;
