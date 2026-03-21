/**
 * UniChat Frontend — API Servis Katmanı
 * Axios instance ve API çağrıları.
 */

import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2 dakika (LLM yanıt süresi uzun olabilir)
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Chat mesajı gönderir.
 * @param {string} message - Kullanıcı mesajı
 * @returns {Promise<{response: string, sources: Array, session_id: string}>}
 */
export async function sendMessage(message) {
  const { data } = await apiClient.post('/api/chat', { message });
  return data;
}

/**
 * Sistem sağlık durumunu kontrol eder.
 * @returns {Promise<{status: string, database: string, ollama: string, embedding: string}>}
 */
export async function checkHealth() {
  const { data } = await apiClient.get('/api/health');
  return data;
}

export default apiClient;
