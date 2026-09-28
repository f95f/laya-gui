import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ConfigPage } from './config.page';
import { ApiService } from './api.service';

describe('ConfigPage', () => {
  const defaultConfig = { questions: { decision: { type: 'choice', instructions: 'Decide.', criteria: { yes: 'Agree.', no: 'Disagree.' } } } };
  let saveConfig: jasmine.Spy;

  beforeEach(async () => {
    saveConfig = jasmine.createSpy('saveConfig').and.callFake(value => of(value));
    await TestBed.configureTestingModule({
      imports: [ConfigPage],
      providers: [{ provide: ApiService, useValue: { getConfig: () => of(defaultConfig), getDefaultConfig: () => of(defaultConfig), saveConfig } }],
    }).compileComponents();
  });

  it('rejects invalid JSON before making a save request', () => {
    const page = TestBed.createComponent(ConfigPage).componentInstance;
    page.editor = '{'; page.save();
    expect(page.error()).toContain('Expected');
    expect(saveConfig).not.toHaveBeenCalled();
  });

  it('saves valid JSON', () => {
    const page = TestBed.createComponent(ConfigPage).componentInstance;
    page.editor = JSON.stringify(defaultConfig); page.save();
    expect(saveConfig).toHaveBeenCalledWith(defaultConfig);
    expect(page.status()).toContain('Saved');
  });
});
