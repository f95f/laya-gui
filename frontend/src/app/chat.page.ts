import { DatePipe, DecimalPipe, JsonPipe, PercentPipe } from '@angular/common';
import { Component, ElementRef, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { ApiService, ChatMessage, ConfigProfile, DecisionResponse, ModelOption } from './api.service';

@Component({ selector: 'app-chat-page', imports: [FormsModule, DatePipe, DecimalPipe, JsonPipe, PercentPipe, LucideAngularModule], templateUrl: './chat.page.html', styleUrl: './chat.page.css' })
export class ChatPage {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  @ViewChild('scrollBody') scrollBody?: ElementRef<HTMLElement>;
  conversationId = signal<string | undefined>(undefined);
  messages = signal<ChatMessage[]>([]);
  configs = signal<ConfigProfile[]>([]);
  models = signal<ModelOption[]>([]);
  selectedConfigId = signal<string | undefined>(undefined);
  selectedModelId = signal<string | undefined>(undefined);
  draft = '';
  busy = signal(false);
  error = signal('');
  copiedId = signal<string | null>(null);

  constructor() {
    this.loadOptions();
    this.route.paramMap.subscribe(params => {
      const id = params.get('id') || undefined;
      this.conversationId.set(id); this.error.set('');
      if (!id) { this.messages.set([]); return; }
      this.api.getConversation(id).subscribe({ next: conversation => { this.messages.set(conversation.messages); this.scrollDown(); }, error: () => this.error.set('Could not load this conversation.') });
    });
  }

  send(): void {
    const message = this.draft.trim();
    if (!message || this.busy()) return;
    this.draft = ''; this.busy.set(true); this.error.set('');
    const optimisticId = `pending-${Date.now()}`;
    this.messages.update(items => [...items, { id: optimisticId, role: 'user', content: message, timestamp: new Date().toISOString() }]);
    this.scrollDown();
    this.api.classify(message, this.conversationId(), this.selectedConfigId(), this.selectedModelId()).subscribe({
      next: result => this.finish(result.conversationId),
      error: err => {
        const savedId = err.error?.detail?.conversationId;
        if (savedId) this.finish(savedId);
        else { this.messages.update(items => items.filter(item => item.id !== optimisticId)); this.draft = message; this.busy.set(false); }
        this.error.set(err.error?.detail?.message || err.error?.detail || 'Could not reach the local API. Start the backend and try again.');
      },
    });
  }

  private finish(id: string): void {
    this.conversationId.set(id); this.busy.set(false); this.api.historyChanged.next();
    this.api.getConversation(id).subscribe({ next: result => { this.messages.set(result.messages); this.scrollDown(); } });
    if (this.router.url !== `/chat/${id}`) this.router.navigate(['/chat', id]);
  }

  private loadOptions(): void {
    this.api.listModels().subscribe({ next: models => {
      this.models.set(models);
      if (!this.selectedModelId() && models.length) this.selectedModelId.set(models[0].id);
    } });
    this.api.listConfigs().subscribe({ next: configs => {
      this.configs.set(configs);
      const active = configs.find(config => config.isActive) || configs[0];
      if (active) {
        this.selectedConfigId.set(active.id);
        this.selectedModelId.set(active.defaultModelId);
      }
    } });
  }

  configChanged(): void {
    const selected = this.configs().find(config => config.id === this.selectedConfigId());
    if (selected) this.selectedModelId.set(selected.defaultModelId);
  }

  onKeydown(event: KeyboardEvent): void { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.send(); } }

  async copy(response: DecisionResponse, id: string): Promise<void> {
    const answer = { choice: response.choice, probability: response.probability, timestamp: response.timestamp,
      probabilities: response.probabilities, confidence: response.confidence, answerConfidence: response.answerConfidence,
      model: response.model, modelId: response.modelId, provider: response.provider, configName: response.configName,
      inputTokens: response.inputTokens, outputTokens: response.outputTokens, latencyMs: response.latencyMs };
    await navigator.clipboard.writeText(JSON.stringify(answer, null, 2));
    this.copiedId.set(id); setTimeout(() => this.copiedId.set(null), 1800);
  }

  private scrollDown(): void { setTimeout(() => this.scrollBody?.nativeElement.scrollTo({ top: this.scrollBody.nativeElement.scrollHeight, behavior: 'smooth' }), 30); }
  probability(value: number | null): string { return value === null ? '-' : `${(value * 100).toFixed(1)}%`; }
  entries(value: Record<string, number>): { key: string; value: number }[] { return Object.entries(value).map(([key, amount]) => ({ key, value: amount })); }
}
