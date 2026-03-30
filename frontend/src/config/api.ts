// Central API configuration
// In development, uses localhost. In production, uses VITE_API_URL env variable.
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default API_BASE;
