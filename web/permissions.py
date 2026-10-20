from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsClinician(BasePermission):
    message = "Only clinicians can perform this action."

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.groups.filter(name="Clinician").exists()
        )


class HasValidRole(BasePermission):
    message = "You must belong to the Patient or Clinician group."

    def has_permission(self, request, view):
        user = request.user

        return (
            user.is_authenticated
            and user.groups.filter(
                name__in=["Patient", "Clinician"]
            ).exists()
        )
    from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsClinicianOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS or request.method == "POST":
            return True

        return user.groups.filter(name="Clinician").exists()