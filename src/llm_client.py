"""Shared LLM client for OpenAI API calls."""

import logging
import os
import time

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Lazy-loaded client
_client = None


def _get_client():
    """Lazy-init OpenAI client."""
    global _client
    if _client is None:
        load_dotenv()
        import openai
        _client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def generate_text(system_prompt: str, user_prompt: str, max_tokens: int = 1000,
                  temperature: float = 0.7) -> str:
    """Call OpenAI API with retry logic.

    Returns generated text, or empty string on failure
    (callers fall back to templates).
    """
    client = _get_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    for attempt in range(2):  # 1 initial + 1 retry
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            elapsed = time.time() - start
            usage = response.usage
            logger.info(
                "LLM call: model=%s tokens=%d/%d latency=%.1fs",
                model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
                elapsed,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("LLM call attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                # Exponential backoff before retry
                time.sleep(2)

    logger.error("LLM call failed after 2 attempts, returning empty string")
    return ""
