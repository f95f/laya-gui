import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService, Dashboard } from './api.service';

@Component({ selector: 'app-dashboard-page', imports: [DatePipe, DecimalPipe, RouterLink], templateUrl: './dashboard.page.html', styleUrl: './dashboard.page.css' })
export class DashboardPage {
  private api = inject(ApiService);
  data = signal<Dashboard | null>(null);
  error = signal('');
  constructor() { this.refresh(); }
  refresh(): void { this.api.getDashboard().subscribe({ next: value => { this.data.set(value); this.error.set(''); }, error: () => this.error.set('Could not load dashboard. Is the backend running?') }); }
  percent(value: number | null): string { return value === null ? '—' : `${(value * 100).toFixed(1)}%`; }
  share(count: number, total: number): number { return total ? count / total * 100 : 0; }
}
