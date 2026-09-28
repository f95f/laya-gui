import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';

@Component({ selector: 'app-config-page', imports: [FormsModule], templateUrl: './config.page.html', styleUrl: './config.page.css' })
export class ConfigPage {
  private api = inject(ApiService);
  editor = '';
  status = signal('');
  error = signal('');
  saving = signal(false);
  constructor() { this.api.getConfig().subscribe({ next: value => this.editor = JSON.stringify(value, null, 2), error: () => this.error.set('Could not load config. Is the backend running?') }); }
  validate(): Record<string, unknown> | null {
    try {
      const value = JSON.parse(this.editor);
      if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('Config must be a JSON object.');
      this.error.set(''); return value;
    } catch (err) { this.error.set(err instanceof Error ? err.message : 'Invalid JSON.'); return null; }
  }
  save(): void {
    const value = this.validate(); if (!value) return;
    this.saving.set(true); this.status.set('');
    this.api.saveConfig(value).subscribe({
      next: config => { this.editor = JSON.stringify(config, null, 2); this.saving.set(false); this.status.set('Saved. New requests will use this config.'); },
      error: err => { this.saving.set(false); this.error.set(err.error?.detail || 'Could not save config.'); },
    });
  }
  reset(): void {
    this.api.getDefaultConfig().subscribe({ next: config => { this.editor = JSON.stringify(config, null, 2); this.status.set('Default loaded. Save to apply it.'); this.error.set(''); } });
  }
}
