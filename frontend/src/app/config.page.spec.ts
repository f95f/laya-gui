import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ApiService } from './api.service';
import { ConfigPage } from './config.page';

describe('ConfigPage', () => {
  const defaultConfig = { questions: { decision: { type: 'choice', instructions: 'Decide.', criteria: { yes: 'Agree.', no: 'Disagree.' } } } };
  const profile = { id: 'config-1', name: 'Default', config: defaultConfig, defaultModelId: 'laya:english', isActive: true, createdAt: '', updatedAt: '' };
  let saveConfigProfile: jasmine.Spy;

  beforeEach(async () => {
    saveConfigProfile = jasmine.createSpy('saveConfigProfile').and.returnValue(of(profile));
    await TestBed.configureTestingModule({
      imports: [ConfigPage],
      providers: [{ provide: ApiService, useValue: {
        listModels: () => of([{ id: 'laya:english', name: 'Laya English', provider: 'laya', model: 'english' }]),
        listConfigs: () => of([profile]),
        getDefaultConfig: () => of(defaultConfig),
        saveConfigProfile,
        createConfigProfile: () => of(profile),
        activateConfigProfile: () => of(profile),
        deleteConfigProfile: () => of({ ok: true }),
      } }],
    }).compileComponents();
  });

  it('rejects invalid JSON before making a save request', () => {
    const page = TestBed.createComponent(ConfigPage).componentInstance;
    page.editor = '{'; page.save();
    expect(page.error()).toContain('Expected');
    expect(saveConfigProfile).not.toHaveBeenCalled();
  });

  it('saves valid JSON', () => {
    const page = TestBed.createComponent(ConfigPage).componentInstance;
    page.editor = JSON.stringify(defaultConfig); page.save();
    expect(saveConfigProfile).toHaveBeenCalled();
    expect(page.status()).toContain('Saved');
  });

  it('opens the active config by default', () => {
    const page = TestBed.createComponent(ConfigPage).componentInstance;
    expect(page.selectedId()).toBe('config-1');
    expect(page.name).toBe('Default');
  });
});
