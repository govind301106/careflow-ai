from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsClinician(BasePermission):
    message = "Only clinicians can perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.groups.filter(name="Clinician").exists():
            return False
        request_record = getattr(user, "clinician_registration", None)
        return request_record is None or request_record.status == "APPROVED"


class HasValidRole(BasePermission):
    message = "You must belong to the Patient or Clinician group."

    def has_permission(self, request, view):
        user = request.user

        if not user.is_authenticated:
            return False
        if user.groups.filter(name="Patient").exists():
            return True
        if not user.groups.filter(name="Clinician").exists():
            return False
        request_record = getattr(user, "clinician_registration", None)
        return request_record is None or request_record.status == "APPROVED"
    from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsClinicianOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS or request.method == "POST":
            return True

        return user.groups.filter(name="Clinician").exists()
