import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs';
import { ApiService, ConversationSummary } from './api.service';
import { LucideAngularModule } from 'lucide-angular';

@Component({ selector: 'app-root', imports: [RouterLink, RouterLinkActive, RouterOutlet, LucideAngularModule], templateUrl: './app.html', styleUrl: './app.css' })
export class App {
  private api = inject(ApiService);
  private router = inject(Router);
  conversations = signal<ConversationSummary[]>([]);
  sidebarOpen = signal(false);
  pageTitle = signal('New chat');
  constructor() {
    this.refresh();
    this.api.historyChanged.subscribe(() => this.refresh());
    this.router.events.pipe(filter(event => event instanceof NavigationEnd)).subscribe(() => this.updateTitle());
    this.updateTitle();
  }
  private refresh(): void {
    this.api.listConversations().subscribe({ next: items => { this.conversations.set(items); this.updateTitle(); }, error: () => this.conversations.set([]) });
  }
  private updateTitle(): void {
    const url = this.router.url;
    if (url.startsWith('/dashboard')) this.pageTitle.set('Dashboard');
    else if (url.startsWith('/config')) this.pageTitle.set('Decision config');
    else this.pageTitle.set(this.conversations().find(item => item.id === url.split('/')[2])?.title || 'New chat');
  }
}
