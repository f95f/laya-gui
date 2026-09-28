import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Subject } from 'rxjs';
export interface DecisionResponse {
  status: string; choice: string | null; probability: number | null; probabilities: Record<string, number>;
  confidence: number | null; answerConfidence: number | null; latencyMs: number | null;
  inputTokens: number | null; outputTokens: number | null; model: string | null;
  routing: unknown; raw: unknown; config: unknown; error: string | null; timestamp: string;
}
export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; timestamp: string; response?: DecisionResponse; }
export interface ConversationSummary { id: string; title: string; created_at: string; updated_at: string; message_count: number; latest_message: string; }
export interface Conversation { id: string; title: string; messages: ChatMessage[]; }
export interface Dashboard {
  stats: { total_requests: number; failed_requests: number; average_latency_ms: number | null; average_confidence: number | null; average_answer_confidence: number | null; input_tokens: number | null; output_tokens: number | null; };
  choices: { choice: string; count: number }[];
  recent: { timestamp: string; choice: string | null; probability: number | null; latencyMs: number; status: string; message: string; conversationId: string; }[];
}
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = 'http://localhost:8000/api';
  historyChanged = new Subject<void>();
  listConversations() { return this.http.get<ConversationSummary[]>(`${this.base}/conversations`); }
  getConversation(id: string) { return this.http.get<Conversation>(`${this.base}/conversations/${id}`); }
  classify(message: string, conversationId?: string) { return this.http.post<{ conversationId: string; requestId: string; responseId: string; response: DecisionResponse }>(`${this.base}/classify`, { message, conversationId }); }
  getConfig() { return this.http.get<Record<string, unknown>>(`${this.base}/config`); }
  getDefaultConfig() { return this.http.get<Record<string, unknown>>(`${this.base}/config/default`); }
  saveConfig(config: Record<string, unknown>) { return this.http.put<Record<string, unknown>>(`${this.base}/config`, config); }
  getDashboard() { return this.http.get<Dashboard>(`${this.base}/dashboard`); }
}
