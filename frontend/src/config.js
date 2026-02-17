// When accessed via tunnel, use the tunnel API URL; otherwise use localhost
const isProduction = window.location.hostname === 'scholia.project2976.xyz'

export const API_BASE = import.meta.env.VITE_API_BASE
  || (isProduction ? 'https://scholia-api.project2976.xyz' : 'http://localhost:8200')
