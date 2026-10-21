export function createCaseRequestGate() {
  let latestRequest = 0;

  return {
    begin() {
      latestRequest += 1;
      return latestRequest;
    },
    isCurrent(requestId) {
      return requestId === latestRequest;
    },
  };
}

export function getReviewForSelectedCase(detail, selectedCaseId) {
  if (!detail || selectedCaseId == null || detail.caseId !== selectedCaseId) return null;
  return detail.clinicianReviews?.[0] ?? null;
}

export function getCaseDetailsForSelection(detail, selectedCaseId) {
  if (!detail || selectedCaseId == null || detail.caseId !== selectedCaseId) return null;
  return detail;
}

export function applyReviewResponseToDetail(detail, selectedCaseId, response) {
  if (!detail || detail.caseId !== selectedCaseId || response?.case_state?.id !== selectedCaseId || !response.id) return detail;
  const review = { ...response };
  delete review.case_state;
  delete review.case_activities;
  return {
    ...detail,
    clinicianReviews: [review],
    activities: response.case_activities || detail.activities,
  };
}
