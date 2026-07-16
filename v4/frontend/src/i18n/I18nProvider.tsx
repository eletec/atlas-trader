'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';

// ── Supported languages ──────────────────────────────────────────────────────
export const SUPPORTED_LANGS: Record<string, string> = {
  fr: 'Français',
  en: 'English',
  de: 'Deutsch',
  es: 'Español',
  it: 'Italiano',
  pt: 'Português',
  nl: 'Nederlands',
  zh: '中文',
};

export type Lang = keyof typeof SUPPORTED_LANGS;

// ── Context ──────────────────────────────────────────────────────────────────
interface I18nContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  loading: boolean;
}

const I18nContext = createContext<I18nContextValue>({
  lang: 'fr',
  setLang: () => {},
  t: (key: string) => key,
  loading: true,
});

// ── Cache ────────────────────────────────────────────────────────────────────
const translationsCache: Record<string, Record<string, string>> = {};

async function loadTranslations(lang: Lang): Promise<Record<string, string>> {
  if (translationsCache[lang]) return translationsCache[lang];
  try {
    const mod = await import(`./translations/${lang}.json`);
    translationsCache[lang] = mod.default || mod;
    return translationsCache[lang];
  } catch {
    // Fallback to French if language file missing
    if (lang !== 'fr') {
      return loadTranslations('fr');
    }
    return {};
  }
}

// ── Get initial language from localStorage ───────────────────────────────────
function getInitialLang(): Lang {
  if (typeof window === 'undefined') return 'fr';
  try {
    const stored = localStorage.getItem('atlas-lang');
    if (stored && stored in SUPPORTED_LANGS) return stored as Lang;
  } catch {}
  // Try browser language
  try {
    const browserLang = navigator.language.slice(0, 2);
    if (browserLang in SUPPORTED_LANGS) return browserLang as Lang;
  } catch {}
  return 'fr';
}

// ── Provider ─────────────────────────────────────────────────────────────────
export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>('fr');
  const [messages, setMessages] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  // Load translations on mount and on lang change
  useEffect(() => {
    const initial = getInitialLang();
    setLangState(initial);
    loadTranslations(initial).then((msgs) => {
      setMessages(msgs);
      setLoading(false);
    });
  }, []);

  const setLang = useCallback((newLang: Lang) => {
    setLangState(newLang);
    setLoading(true);
    try {
      localStorage.setItem('atlas-lang', newLang);
    } catch {}
    loadTranslations(newLang).then((msgs) => {
      setMessages(msgs);
      setLoading(false);
    });
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      let text = messages[key];
      if (text === undefined || text === null) {
        // Try fallback to French
        if (lang !== 'fr') {
          const frCache = translationsCache['fr'];
          if (frCache && frCache[key] !== undefined) {
            text = frCache[key];
          }
        }
        if (text === undefined || text === null) return key;
      }
      if (vars) {
        Object.entries(vars).forEach(([k, v]) => {
          text = text!.replace(`{${k}}`, String(v));
        });
      }
      return text;
    },
    [messages, lang],
  );

  return (
    <I18nContext.Provider value={{ lang, setLang, t, loading }}>
      {children}
    </I18nContext.Provider>
  );
}

// ── Hook ─────────────────────────────────────────────────────────────────────
export function useTranslation() {
  return useContext(I18nContext);
}

export default I18nProvider;
