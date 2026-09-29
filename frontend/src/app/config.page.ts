import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, ConfigProfile, ModelOption } from './api.service';

@Component({ selector: 'app-config-page', imports: [FormsModule], templateUrl: './config.page.html', styleUrl: './config.page.css' })
export class ConfigPage {
  private api = inject(ApiService);
  configs = signal<ConfigProfile[]>([]);
  models = signal<ModelOption[]>([]);
  selectedId = signal('');
  showLibrary = signal(false);
  name = '';
  defaultModelId = 'laya:english';
  editor = '';
  status = signal('');
  error = signal('');
  saving = signal(false);

  constructor() { this.load(); }

  load(selectId?: string, statusAfterLoad = ''): void {
    this.api.listModels().subscribe({ next: models => this.models.set(models) });
    this.api.listConfigs().subscribe({
      next: configs => {
        this.configs.set(configs);
        const selected = configs.find(config => config.id === selectId) || configs.find(config => config.isActive) || configs[0];
        if (selected) {
          this.open(selected.id);
          if (statusAfterLoad) this.status.set(statusAfterLoad);
        }
      },
      error: () => this.error.set('Could not load configs. Is the backend running?'),
    });
  }

  activeConfig(): ConfigProfile | undefined { return this.configs().find(config => config.isActive); }
  selectedConfig(): ConfigProfile | undefined { return this.configs().find(config => config.id === this.selectedId()); }
  selectedIsActive(): boolean { return this.selectedConfig()?.isActive || false; }
  modelName(modelId: string): string { return this.models().find(model => model.id === modelId)?.name || modelId; }
  criteriaCount(config: ConfigProfile): number {
    const questions = (config.config['questions'] || {}) as Record<string, { criteria?: Record<string, string> }>;
    return Object.values(questions).reduce((count, question) => count + Object.keys(question.criteria || {}).length, 0);
  }

  open(id: string): void {
    const selected = this.configs().find(config => config.id === id);
    if (!selected) return;
    this.selectedId.set(selected.id);
    this.name = selected.name;
    this.defaultModelId = selected.defaultModelId;
    this.editor = JSON.stringify(selected.config, null, 2);
    this.status.set('');
    this.error.set('');
    this.showLibrary.set(false);
  }

  validate(): Record<string, unknown> | null {
    try {
      const value = JSON.parse(this.editor);
      if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('Config must be a JSON object.');
      this.error.set(''); return value;
    } catch (err) { this.error.set(err instanceof Error ? err.message : 'Invalid JSON.'); return null; }
  }

  save(): void {
    const value = this.validate(); if (!value || !this.selectedId()) return;
    this.saving.set(true); this.status.set('');
    this.api.saveConfigProfile(this.selectedId(), {
      name: this.name.trim() || 'Untitled config', config: value,
      defaultModelId: this.defaultModelId, isActive: this.selectedIsActive(),
    }).subscribe({
      next: config => { this.saving.set(false); this.load(config.id, 'Saved.'); },
      error: err => { this.saving.set(false); this.error.set(err.error?.detail || 'Could not save config.'); },
    });
  }

  newConfig(): void {
    this.api.getDefaultConfig().subscribe({ next: config => {
      this.saving.set(true); this.status.set('');
      this.api.createConfigProfile({
        name: 'New decision config', config, defaultModelId: this.defaultModelId || 'laya:english', isActive: false,
      }).subscribe({
        next: created => { this.saving.set(false); this.load(created.id, 'New config created.'); },
        error: err => { this.saving.set(false); this.error.set(err.error?.detail || 'Could not create config.'); },
      });
    } });
  }

  duplicate(config = this.selectedConfig()): void {
    if (!config) return;
    this.saving.set(true); this.status.set('');
    this.api.createConfigProfile({
      name: `${config.name} copy`, config: config.config, defaultModelId: config.defaultModelId, isActive: false,
    }).subscribe({
      next: created => { this.saving.set(false); this.load(created.id, 'Duplicated.'); },
      error: err => { this.saving.set(false); this.error.set(err.error?.detail || 'Could not duplicate config.'); },
    });
  }

  activate(id = this.selectedId()): void {
    if (!id) return;
    this.api.activateConfigProfile(id).subscribe({
      next: config => { this.load(config.id, 'Active config updated.'); },
      error: err => this.error.set(err.error?.detail || 'Could not activate config.'),
    });
  }

  delete(config: ConfigProfile): void {
    if (config.isActive) { this.error.set('Activate another config before deleting this one.'); return; }
    this.saving.set(true); this.status.set('');
    this.api.deleteConfigProfile(config.id).subscribe({
      next: () => { this.saving.set(false); this.load(undefined, 'Config deleted.'); },
      error: err => { this.saving.set(false); this.error.set(err.error?.detail || 'Could not delete config.'); },
    });
  }

  reset(): void {
    this.api.getDefaultConfig().subscribe({ next: config => { this.editor = JSON.stringify(config, null, 2); this.status.set('Default loaded. Save to apply it.'); this.error.set(''); } });
  }
}
