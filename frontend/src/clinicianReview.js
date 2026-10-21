export function validateClinicianReview(formData, workflowAction) {
  if (workflowAction === "request_information" && !String(formData.get("patient_request") || "").trim()) {
    return "Enter the specific question or information needed from the patient.";
  }
  if (workflowAction === "escalate" && !String(formData.get("escalation_reason") || "").trim()) {
    return "Enter a reason for handing this case off.";
  }
  if (workflowAction === "finalize" && !String(formData.get("patient_comments") || "").trim()) {
    return "Add comments for the patient before finalizing this review.";
  }
  return "";
}

export function buildClinicianReviewPayload(formData, workflowAction) {
  return {
    workflow_action: workflowAction,
    decision: workflowAction === "finalize" ? "APPROVED" : "IN_REVIEW",
    reviewer_comments: formData.get("comments") || "",
    patient_comments: formData.get("patient_comments") || "",
    follow_up_instructions: formData.get("follow_up") || "",
    referral_details: formData.get("referral") || "",
    patient_request: formData.get("patient_request") || "",
    escalation_reason: formData.get("escalation_reason") || "",
  };
}
