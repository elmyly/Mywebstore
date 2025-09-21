import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from flask import current_app
from .database import get_db, release_db

GOOGLE_AI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"


def _extract_text(payload: dict) -> Optional[str]:
    try:
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                text = part.get("text")
                if text:
                    return text.strip()
    except AttributeError:
        return None
    return None


def ask_faq_ai(app, question: str) -> str:
    question = question.strip()
    if not question:
        return "Merci de saisir une question avant d'envoyer."

    api_key = app.config.get("FAQ_AI_API_KEY")
    if not api_key:
        app.logger.warning("FAQ AI API key missing; returning fallback message")
        return (
            "Merci pour votre question ! Notre équipe vous répondra très vite."
        )

    # Pull optional AI context written by admin
    context_text = ""
    try:
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT value FROM ai_settings WHERE key='faq_context'")
        row = cur.fetchone()
        context_text = (row[0] or "") if row else ""
    except Exception:
        pass
    finally:
        try:
            release_db(conn)
        except Exception:
            pass

    if context_text:
        prompt = (
            "Tu es l'assistant du magasin Bghitha. Utilise le contexte suivant pour répondre :\n"
            f"{context_text}\n\n"
            "Réponds en français à la question ci-dessous en 2–3 phrases maximum, précises et utiles.\n"
            f"Question: {question}"
        )
    else:
        prompt = (
            "Tu es l'assistant du magasin Bghitha. Réponds en français à la question suivante en 2–3 phrases utiles :\n"
            f"{question}"
        )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 256,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    url = f"{GOOGLE_AI_ENDPOINT}?key={api_key}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        app.logger.exception("FAQ AI HTTP error: %s", err)
        return (
            "Impossible de contacter l'assistant pour le moment. Essayez à nouveau dans un instant."
        )
    except Exception as exc:
        app.logger.exception("FAQ AI request failed: %s", exc)
        return (
            "Nous rencontrons un souci technique. Votre question a bien été transmise à l'équipe."
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        app.logger.error("FAQ AI response not JSON: %s", body[:200])
        return (
            "Réponse inattendue de l'assistant. Nous reviendrons vers vous rapidement."
        )

    text = _extract_text(payload)
    if not text:
        app.logger.warning("FAQ AI response missing text: %s", payload)
        return (
            "Merci ! Nous reviendrons vers vous très vite avec une réponse plus détaillée."
        )

    return text


__all__ = ["ask_faq_ai"]
