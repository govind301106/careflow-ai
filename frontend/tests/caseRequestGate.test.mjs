import assert from "node:assert/strict";
import test from "node:test";
import { createCaseRequestGate, getReviewForSelectedCase, getCaseDetailsForSelection } from "../src/caseRequestGate.js";

test("switching cases prevents a slower previous response from replacing current details", () => {
  const gate = createCaseRequestGate();
  const firstCaseRequest = gate.begin();
  const secondCaseRequest = gate.begin();

  assert.equal(gate.isCurrent(firstCaseRequest), false);
  assert.equal(gate.isCurrent(secondCaseRequest), true);
});

test("a retry supersedes the prior request for the selected case", () => {
  const gate = createCaseRequestGate();
  const failedRequest = gate.begin();
  const retryRequest = gate.begin();

  assert.equal(gate.isCurrent(failedRequest), false);
  assert.equal(gate.isCurrent(retryRequest), true);
});

test("an initial render with no selected case does not dereference empty detail state", () => {
  assert.equal(getReviewForSelectedCase(null, undefined), null);
  assert.equal(getReviewForSelectedCase(null, 12), null);
});

test("review detail is only taken from the selected case", () => {
  const review = { decision: "APPROVED" };
  const detail = { caseId: 12, clinicianReviews: [review] };

  assert.equal(getReviewForSelectedCase(detail, 12), review);
  assert.equal(getReviewForSelectedCase(detail, 13), null);
});

test("switching cases never renders prior AI results or review details", () => {
  const first = { caseId: 12, aiResults: [{ id: "old-ai" }], patientAI: { status: "completed" }, clinicianReviews: [{ id: "old-review" }] };
  assert.equal(getCaseDetailsForSelection(first, 13), null);
  assert.equal(getCaseDetailsForSelection(first, 12), first);
});
