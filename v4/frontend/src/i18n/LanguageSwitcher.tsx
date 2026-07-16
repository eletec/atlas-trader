'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useTranslation, SUPPORTED_LANGS, Lang } from './I18nProvider';

export default function LanguageSwitcher() {
  const { lang, setLang } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div ref={ref} className="relative inline-block text-left">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800/80 px-2.5 py-1.5 text-xs text-slate-300 hover:border-slate-600 hover:text-white transition-colors"
        title="Change language"
      >
        <span className="text-base">🌐</span>
        <span>{SUPPORTED_LANGS[lang]}</span>
        <svg className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-1 w-40 origin-top-right rounded-md border border-slate-700 bg-slate-900 shadow-xl ring-1 ring-black ring-opacity-5">
          <div className="py-1">
            {Object.entries(SUPPORTED_LANGS).map(([code, name]) => (
              <button
                key={code}
                onClick={() => { setLang(code as Lang); setOpen(false); }}
                className={`block w-full px-3 py-1.5 text-left text-xs transition-colors ${
                  lang === code
                    ? 'bg-indigo-600/30 text-white font-medium'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                {lang === code && '✓ '}{name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
