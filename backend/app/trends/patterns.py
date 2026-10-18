"""S8: which hooks and formats win on YouTube (lift), and which hooks active LinkedIn voices use.
Audience voice: questions, objections and requests in comments of the top videos."""
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from .contracts import AudienceTheme, Pattern
from .scoring import Item

LABELS = {
    "hook:question": "Pregunta en el título / Question in the title",
    "hook:number": "Número en el gancho / Number in the hook",
    "hook:result_first": "Resultado medible primero / Measurable result first",
    "hook:how_to": "Cómo hacer / How-to",
    "hook:contrarian": "Contrario a lo esperado / Contrarian take",
    "hook:news": "Noticia o lanzamiento / News or launch",
    "hook:story": "Historia personal / Personal story",
    "hook:list": "Lista / Listicle",
    "hook:tutorial": "Tutorial paso a paso / Step-by-step tutorial",
    "format:short": "Formato corto (≤ 3 min) / Short format",
    "format:long": "Formato largo / Long format",
    "title:digit": "Cifra en el título / Digit in the title",
    "title:first_person": "Primera persona / First person",
}
_FIRST_PERSON = re.compile(r"\b(i|my|me|yo|mi|mis|probé|hice|tested)\b", re.I)


def features(it: Item, title: str) -> set[str]:
    f = {f"format:{it.format}"}
    if it.hook and it.hook != "other":
        f.add(f"hook:{it.hook}")
    if re.search(r"\d", title or ""):
        f.add("title:digit")
    if _FIRST_PERSON.search(title or ""):
        f.add("title:first_person")
    return f


def youtube_lift(items: list[Item], titles: dict[str, str], li_top: list[Item],
                 min_support: int = 8, min_lift: float = 1.3) -> list[Pattern]:
    yt = [it for it in items if it.platform == "youtube" and it.outlier() is not None]
    winners = [it for it in yt if it.outlier() >= 2]
    if len(yt) < 20 or len(winners) < min_support:
        return []
    feats = {it.item_id: features(it, titles.get(it.item_id, "")) for it in yt}
    all_c = Counter(f for it in yt for f in feats[it.item_id])
    win_c = Counter(f for it in winners for f in feats[it.item_id])
    li_hooks = Counter(f"hook:{it.hook}" for it in li_top if it.hook)
    out = []
    for f, n_win in win_c.items():
        lift = (n_win / len(winners)) / (all_c[f] / len(yt))
        if n_win >= min_support and lift >= min_lift:
            examples = sorted((it for it in winners if f in feats[it.item_id]),
                              key=lambda it: it.outlier(), reverse=True)[:3]
            out.append(Pattern(
                pattern=f, label=LABELS.get(f, f), evidence="youtube_lift", lift=round(lift, 2),
                support=n_win,
                also_used_by_active_linkedin_voices=bool(li_top) and li_hooks[f] / len(li_top) >= 0.15,
                examples=[e.item_id for e in examples]))
    return sorted(out, key=lambda p: p.lift or 0, reverse=True)[:8]


def linkedin_usage(li_top: list[Item]) -> list[Pattern]:
    """Hooks most used by the most visible LinkedIn posts. Usage, not proven performance."""
    if len(li_top) < 10:
        return []
    c = Counter(it.hook for it in li_top if it.hook and it.hook != "other")
    out = []
    for hook, n in c.most_common(3):
        if n / len(li_top) >= 0.15:
            ex = [it.item_id for it in li_top if it.hook == hook][:3]
            out.append(Pattern(pattern=f"hook:{hook}", label=LABELS.get(f"hook:{hook}", hook),
                               evidence="linkedin_usage", lift=None, support=n,
                               also_used_by_active_linkedin_voices=True, examples=ex))
    return out


# --- Audience voice -----------------------------------------------------------
class Theme(BaseModel):
    theme: str
    type: Literal["question", "objection", "request"]
    mentions: int
    topic_id: str     # "none" if it fits no topic


class ThemeList(BaseModel):
    themes: list[Theme]


def audience_voice(llm, yt, top_videos: list[Item], topic_catalog: str, main_lang: str) -> list[AudienceTheme]:
    comments = []
    for it in top_videos[:10]:
        try:
            comments += [(it.topic_id, c) for c in yt.top_comments(it.item_id.removeprefix("yt:"), 60)]
        except Exception:
            continue
    if len(comments) < 20:
        return []
    text = "\n".join(f"[{t}] {c[:240]}" for t, c in comments[:600])
    res = llm.sonnet(
        "You summarize what an audience asks for in comments. Count mentions honestly. "
        "Ignore praise, spam and anything about the creator personally. Never quote or name commenters.",
        f"Topic catalog:\n{topic_catalog}\n\nComments (prefixed with the video's topic id):\n{text}\n\n"
        f"Return up to 8 recurring themes in {main_lang}: questions, objections or requests, "
        "each with an approximate mention count and the best-fitting topic id.",
        ThemeList, effort="low", max_tokens=8000)
    return [AudienceTheme(theme=t.theme, mentions=t.mentions, type=t.type,
                          topic_id=None if t.topic_id == "none" else t.topic_id)
            for t in res.themes if t.mentions >= 3]
