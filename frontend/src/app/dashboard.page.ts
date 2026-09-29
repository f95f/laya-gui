import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService, ConfigProfile, Dashboard, ModelOption } from './api.service';

@Component({ selector: 'app-dashboard-page', imports: [DatePipe, DecimalPipe, RouterLink, FormsModule], templateUrl: './dashboard.page.html', styleUrl: './dashboard.page.css' })
export class DashboardPage {
  private api = inject(ApiService);
  data = signal<Dashboard | null>(null);
  configs = signal<ConfigProfile[]>([]);
  models = signal<ModelOption[]>([]);
  configId = '';
  modelId = '';
  error = signal('');
  constructor() {
    this.api.listConfigs().subscribe({ next: value => this.configs.set(value) });
    this.api.listModels().subscribe({ next: value => this.models.set(value) });
    this.refresh();
  }
  refresh(): void { this.api.getDashboard(this.configId || undefined, this.modelId || undefined).subscribe({ next: value => { this.data.set(value); this.error.set(''); }, error: () => this.error.set('Could not load dashboard. Is the backend running?') }); }
  percent(value: number | null): string { return value === null ? '-' : `${(value * 100).toFixed(1)}%`; }
  share(count: number, total: number): number { return total ? count / total * 100 : 0; }
}
