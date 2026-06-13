"""
v6/core/reflection_engine.py — V6 Reflection Engine.

Analyse les trades perdants pour identifier des patterns d'échec récurrents
et suggérer des ajustements de paramètres. L'IA passe de "signal cosmétique"
à "research assistant" (GPT, Claude, DeepSeek consensus).

Fonctionnement :
1. Tous les N trades clôturés → collecte des perdants
2. Construction d'un prompt structuré avec le contexte de chaque trade
3. Appel LLM (DeepSeek) pour identifier les patterns communs
4. Suggestions d'ajustement de seuils (validées par l'humain ou auto avec limites)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("v6.core.reflection_engine")


class ReflectionEngine:
    """
    Moteur de réflexion asynchrone.
    
    Stocke les suggestions dans /app/data/v6_reflections.json
    et les expose au dashboard / à l'admin.
    """

    def __init__(self, db_path: str = "/app/data/v4.db"):
        self.db_path = db_path
        self.reflections_path = Path("/app/data/v6_reflections.json")
        self._lock = threading.Lock()
        self._pending = False

    def collect_losing_trades(self, n: int = 20) -> list[dict]:
        """Récupère les N derniers trades perdants."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT symbol, action, entry_price, exit_price, pnl_usd,
                          timestamp, exit_reason, dag_id
                   FROM v4_trades
                   WHERE status = 'closed' AND pnl_usd < 0
                   ORDER BY timestamp DESC
                   LIMIT ?""", (n,)
            ).fetchall()
            conn.close()
            return [
                {
                    "symbol": r[0], "action": r[1], "entry": r[2],
                    "exit": r[3], "pnl": r[4], "timestamp": r[5],
                    "exit_reason": r[6], "dag_id": r[7],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Reflection: DB error: %s", e)
            return []

    def build_prompt(self, losing_trades: list[dict]) -> str:
        """Construit un prompt structuré pour le LLM."""
        if not losing_trades:
            return ""

        by_symbol: dict[str, list] = {}
        for t in losing_trades:
            sym = t.get("symbol", "?")
            by_symbol.setdefault(sym, []).append(t)

        prompt = (
            "You are a quantitative trading analyst reviewing losing trades.\n\n"
            f"## Recent Losing Trades ({len(losing_trades)} total)\n\n"
        )

        for symbol, trades in by_symbol.items():
            prompt += f"### {symbol} ({len(trades)} trades)\n"
            total_loss = sum(t.get("pnl", 0) for t in trades)
            reasons = set(t.get("exit_reason", "?") for t in trades)
            prompt += f"Total loss: ${total_loss:.2f}\n"
            prompt += f"Exit reasons: {', '.join(reasons)}\n\n"

            for t in trades[:5]:  # max 5 par actif
                prompt += (
                    f"- {t['timestamp'][:16]} | {t['action']} | "
                    f"Entry ${t['entry']:.2f} → Exit ${t['exit']:.2f} | "
                    f"PnL ${t['pnl']:.2f} | {t['exit_reason']}\n"
                )
            prompt += "\n"

        prompt += (
            "## Questions:\n"
            "1. What common patterns do you see across these losing trades?\n"
            "2. Are there specific market conditions (regime, time of day, volatility) "
            "where the strategy consistently fails?\n"
            "3. Suggest 1-3 parameter adjustments (threshold, SL multiplier, "
            "time-stop hours) that could reduce these losses.\n"
            "4. Format your parameter suggestions as JSON:\n"
            '   {"adjustments": [{"param": "...", "symbol": "...", "current": X, "suggested": Y, "reason": "..."}]}\n'
        )

        return prompt

    def analyze(self, callback=None) -> dict | None:
        """
        Lance une analyse asynchrone des trades perdants.
        
        Args:
            callback: fonction appelée avec le résultat (optionnel)
        """
        if self._pending:
            logger.info("Reflection: already analyzing, skip")
            return None

        trades = self.collect_losing_trades(20)
        if len(trades) < 5:
            logger.info("Reflection: pas assez de trades perdants (<5), skip")
            return None

        prompt = self.build_prompt(trades)
        if not prompt:
            return None

        self._pending = True

        def _run():
            try:
                result = self._call_llm(prompt)
                self._save_reflection(result, trades)
                if callback:
                    callback(result)
            except Exception as e:
                logger.warning("Reflection LLM failed: %s", e)
            finally:
                self._pending = False

        threading.Thread(target=_run, daemon=True, name="reflection_engine").start()
        return {"status": "analyzing", "n_trades": len(trades)}

    def _call_llm(self, prompt: str) -> dict:
        """Appelle le LLM pour analyser les trades."""
        from v4.nodes.config_loader import load_v4_config
        
        _llm_cfg = load_v4_config(None, "llm", {
            "provider": "deepseek", "model": "deepseek-v4-pro",
        })
        
        try:
            import litellm
            litellm.drop_params = True
            resp = litellm.completion(
                model=f"{_llm_cfg.get('provider','deepseek')}/{_llm_cfg.get('model','deepseek-v4-pro')}",
                messages=[
                    {"role": "system", "content": "You are a quantitative trading analyst. Respond with clear, actionable insights."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
                timeout=120,
            )
            text = resp.choices[0].message.content if resp.choices else ""

            # Extraire le JSON des suggestions
            suggestions = []
            try:
                if "```json" in text:
                    json_str = text.split("```json", 1)[1].split("```", 1)[0]
                elif "{" in text:
                    json_str = text[text.find("{"):text.rfind("}") + 1]
                else:
                    json_str = "{}"
                parsed = json.loads(json_str)
                suggestions = parsed.get("adjustments", [])
            except (json.JSONDecodeError, ValueError):
                pass

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "analysis": text[:2000],
                "suggestions": suggestions,
            }
        except Exception as e:
            logger.warning("Reflection litellm error: %s", e)
            return {"error": str(e)}

    def _save_reflection(self, result: dict, trades: list[dict]):
        """Sauvegarde la réflexion dans le fichier JSON."""
        with self._lock:
            existing = []
            if self.reflections_path.exists():
                try:
                    existing = json.loads(self.reflections_path.read_text())
                except Exception:
                    pass
            
            existing.append({
                **result,
                "n_trades_analyzed": len(trades),
                "symbols": list(set(t.get("symbol", "?") for t in trades)),
            })
            
            # Garder les 50 dernières
            existing = existing[-50:]
            self.reflections_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    def get_latest(self) -> dict | None:
        """Retourne la dernière réflexion."""
        if not self.reflections_path.exists():
            return None
        try:
            reflections = json.loads(self.reflections_path.read_text())
            return reflections[-1] if reflections else None
        except Exception:
            return None
