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
