
const API_URL =
    import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";



async function getCsrfToken() {
    const response = await fetch(`${API_URL}/csrf/`, {
        credentials: "include",
    });

    if (!response.ok) {
        throw new Error("Could not obtain the CSRF token.");
    }

    // Prefer Django's masked token if available.
    const cookieToken = document.cookie
        .split("; ")
        .find((cookie) => cookie.startsWith("csrftoken="))
        ?.split("=")
        .slice(1)
        .join("=");

    if (!cookieToken) {
        throw new Error(
            "CSRF cookie missing. Check browser cookie settings and CORS."
        );
    }

    return decodeURIComponent(cookieToken);
}



export async function apiRequest(endpoint, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = { ...options.headers };

    if (!(options.body instanceof FormData) && options.body) {
        headers["Content-Type"] = "application/json";
    }

    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        headers["X-CSRFToken"] = await getCsrfToken();
    }
    
    const response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
        method,
        headers,
        credentials: "include",
    });

    const data = await response.json().catch(() => null);

    if (!response.ok) {
        throw new Error(
            data?.detail || JSON.stringify(data) || `Request failed: ${response.status}`
        );
    }

    return data;
}
