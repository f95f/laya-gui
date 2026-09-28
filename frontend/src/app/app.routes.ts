import { Routes } from '@angular/router';
import { ChatPage } from './chat.page';
import { ConfigPage } from './config.page';
import { DashboardPage } from './dashboard.page';
export const routes: Routes = [
  { path: 'chat', component: ChatPage }, { path: 'chat/:id', component: ChatPage },
  { path: 'config', component: ConfigPage }, { path: 'dashboard', component: DashboardPage },
  { path: '', pathMatch: 'full', redirectTo: 'chat' }, { path: '**', redirectTo: 'chat' },
];
