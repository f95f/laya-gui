import { ApplicationConfig, importProvidersFrom, provideBrowserGlobalErrorListeners, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { routes } from './app.routes';
import { LucideAngularModule, Plus, LayoutDashboard, Settings2, Menu, X, ArrowUp, Copy, Check, ChevronDown } from 'lucide-angular';
export const appConfig: ApplicationConfig = { providers: [provideBrowserGlobalErrorListeners(), provideZoneChangeDetection({ eventCoalescing: true }), provideHttpClient(), provideRouter(routes), importProvidersFrom(LucideAngularModule.pick({ Plus, LayoutDashboard, Settings2, Menu, X, ArrowUp, Copy, Check, ChevronDown }))] };
