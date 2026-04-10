// Single source of truth for the backend API base URL.
// Import this constant from any file that makes fetch calls to the backend.
// Do NOT import from app/ or components/ — this file must remain dependency-free
// to avoid circular imports.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
