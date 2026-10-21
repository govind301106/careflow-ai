import test from "node:test";
import assert from "node:assert/strict";
import { buildClinicianReviewPayload, validateClinicianReview } from "../src/clinicianReview.js";

function form(values) {
  return { get: (key) => values[key] ?? "" };
}

test("review actions build the supported payload and preserve entered patient and handoff text", () => {
  const values = form({ comments: "Private note", patient_comments: "Please follow up", follow_up: "In one week", referral: "Cardiology", patient_request: "When did this start?", escalation_reason: "Needs specialist" });
  assert.deepEqual(buildClinicianReviewPayload(values, "save_draft"), {
    workflow_action: "save_draft", decision: "IN_REVIEW", reviewer_comments: "Private note", patient_comments: "Please follow up",
    follow_up_instructions: "In one week", referral_details: "Cardiology", patient_request: "When did this start?", escalation_reason: "Needs specialist",
  });
  assert.equal(buildClinicianReviewPayload(values, "finalize").decision, "APPROVED");
  assert.equal(buildClinicianReviewPayload(values, "request_information").patient_request, "When did this start?");
  assert.equal(buildClinicianReviewPayload(values, "escalate").escalation_reason, "Needs specialist");
});

test("workflow-specific required text is validated before sending", () => {
  assert.match(validateClinicianReview(form({}), "request_information"), /specific question/);
  assert.match(validateClinicianReview(form({}), "escalate"), /reason/);
  assert.match(validateClinicianReview(form({}), "finalize"), /comments for the patient/);
  assert.equal(validateClinicianReview(form({ patient_request: "  question  ", escalation_reason: "handoff", patient_comments: "reviewed" }), "request_information"), "");
  assert.equal(validateClinicianReview(form({ patient_request: "question", escalation_reason: "handoff", patient_comments: "reviewed" }), "escalate"), "");
  assert.equal(validateClinicianReview(form({ patient_request: "question", escalation_reason: "handoff", patient_comments: "reviewed" }), "finalize"), "");
});
