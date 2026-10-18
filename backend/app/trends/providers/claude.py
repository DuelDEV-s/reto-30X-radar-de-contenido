"""Claude API: Haiku 5.5 for bulk classification, Sonnet 5.5 for judgment, and the configurable
top model (Sonnet 5.5 by default, Opus 5.5 with RADAR_TOP_MODEL=opus) for the topic taxonomy and
the content proposals."""
import asyncio
import logging

import anthropic
from pydantic import BaseModel

from .. import config

log = logging.getLogger(__name__)

# Opus and Sonnet requests opt into server-side refusal fallbacks (routes by refusal category).
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM:
    def __init__(self):
        config.secret("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(max_retries=4)
        self.aclient = anthropic.AsyncAnthropic(max_retries=4)
        self.usd = 0.0
        self.calls = 0

    def _account(self, model: str, usage) -> None:
        price_in, price_out = config.PRICES.get(model, config.PRICES[config.OPUS])
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.usd += (usage.input_tokens * price_in + cached * price_in * 0.1
                     + written * price_in * 1.25 + usage.output_tokens * price_out) / 1e6
        self.calls += 1

    def top(self, system: str, prompt: str, schema: type[BaseModel],
            effort: str = "medium", max_tokens: int = 32000) -> BaseModel:
        """Top model: where output quality is visible (taxonomy, proposals)."""
        return self._structured(config.top_model(), system, prompt, schema, effort, max_tokens)

    def sonnet(self, system: str, prompt: str, schema: type[BaseModel],
               effort: str = "medium", max_tokens: int = 32000) -> BaseModel:
        """Sonnet: routine judgment (queries, persona rubric, comment themes)."""
        return self._structured(config.judgment_model(), system, prompt, schema, effort, max_tokens)

    def _structured(self, model: str, system: str, prompt: str, schema: type[BaseModel],
                    effort: str, max_tokens: int) -> BaseModel:
        """One structured call. The system prompt is cached for repeated calls."""
        common = dict(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort},
            output_format=schema,
        )
        if model == config.HAIKU:
            # Haiku has no server-side refusal fallback, so it goes through the regular endpoint.
            with self.client.messages.stream(**common) as stream:
                msg = stream.get_final_message()
        else:
            with self.client.beta.messages.stream(
                    betas=[FALLBACK_BETA], fallbacks="default", **common) as stream:
                msg = stream.get_final_message()
        self._account(model, msg.usage)
        if msg.stop_reason == "refusal" or msg.parsed_output is None:
            raise RuntimeError(f"{model} returned no parsed output (stop_reason={msg.stop_reason})")
        return msg.parsed_output

    async def _haiku_one(self, sem, system, prompt, schema, max_tokens):
        async with sem:
            try:
                msg = await self.aclient.messages.parse(
                    model=config.HAIKU,
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": prompt}],
                    output_config={"effort": "low"},
                    output_format=schema,
                )
            except anthropic.APIError as e:
                log.warning("haiku call failed: %s", e)
                return None
            self._account(config.HAIKU, msg.usage)
            return msg.parsed_output if msg.stop_reason != "refusal" else None

    def haiku_many(self, system: str, prompts: list[str], schema: type[BaseModel],
                   max_tokens: int = 8000, concurrency: int = 8) -> list[BaseModel | None]:
        """Parallel structured Haiku calls; failed calls come back as None."""
        async def run():
            sem = asyncio.Semaphore(concurrency)
            return await asyncio.gather(*(self._haiku_one(sem, system, p, schema, max_tokens)
                                          for p in prompts))
        return asyncio.run(run())
