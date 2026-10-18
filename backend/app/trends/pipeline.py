"""Runs step 2 end to end for one brand identity and stores the report."""
import json
import logging
import math
from collections import Counter
from datetime import timedelta

from . import bootstrap, collect, config, db as store, linkedin, normalize, opportunities as opp_mod
from . import patterns as pat, planner, scoring, topics as topic_mod
from .contracts import (BrandIdentity, BrandInfo, Cost, DataQuality, Demand, Item as OutItem,
                        ItemMetrics, LinkedInSource, LinkedInTopic, Report, RunInfo, Sources, Topic,
                        WeekAttention, WeekPosts, Window, YouTubeSource)
from .providers.claude import LLM
from .providers.search import SearchSpend
from .providers.youtube import QuotaExceeded, YouTube

log = logging.getLogger(__name__)
N_QUERIES = 28
DATE_ORDER_QUERIES = 6
TOP_TOPICS_JUDGED = 30
TOP_OPPORTUNITIES = 8


class Run:
    def __init__(self, identity: BrandIdentity, run_id: str | None = None, on_stage=None):
        self.identity = identity
        self.on_stage = on_stage    # callback(stage_name) so the caller can mirror progress
        self.item_topics: dict[str, str] = {}
        self.db = store.connect()
        self.now = store.now_utc()
        self.run_id = run_id or f"r_{self.now:%Y%m%d%H%M%S}_{identity.brand_id}"
        self.warnings: list[str] = []
        self.llm = LLM()
        self.yt = YouTube(self.db)
        self.spend = SearchSpend()
        self.db.execute("INSERT OR REPLACE INTO runs (run_id, brand_id, started_at, status, stage) "
                        "VALUES (?,?,?,?,?)", (self.run_id, identity.brand_id, store.iso(self.now),
                                               "running", "start"))
        self.db.execute("INSERT OR REPLACE INTO brands VALUES (?,?,?,?,?)",
                        (identity.brand_id, identity.brand_name, identity.model_dump_json(), None,
                         store.iso(self.now)))
        self.db.commit()

    def stage(self, name: str) -> None:
        log.info("[%s] %s", self.run_id, name)
        self.db.execute("UPDATE runs SET stage=? WHERE run_id=?", (name, self.run_id))
        self.db.commit()
        if self.on_stage:
            self.on_stage(name)

    def spent(self) -> float:
        return self.llm.usd + self.spend.usd

    # ------------------------------------------------------------------------
    def execute(self) -> Report:
        try:
            report = self._execute()
        except Exception as e:
            self.db.execute("UPDATE runs SET status='failed', error=?, finished_at=? WHERE run_id=?",
                            (repr(e)[:2000], store.iso(store.now_utc()), self.run_id))
            self.db.commit()
            raise
        self.db.execute(
            "UPDATE runs SET status='done', stage='done', finished_at=?, cost=?, report=? WHERE run_id=?",
            (store.iso(store.now_utc()), json.dumps({"search": self.spend.usd, "llm": self.llm.usd,
                                                     "youtube_units": self.yt.units}),
             report.to_json(), self.run_id))
        self.db.commit()
        return report

    def _execute(self) -> Report:
        idn, db = self.identity, self.db
        markets = bootstrap.markets(idn)
        langs = bootstrap.query_languages(markets)
        main_lang = markets.languages[0]

        self.stage("bootstrap")
        try:
            cov_source, cov_texts = bootstrap.coverage(db, idn, self.yt, self.spend)
        except Exception as e:
            cov_source, cov_texts = None, []
            self.warnings.append(f"Coverage lookup failed: {e}")
        voice = bootstrap.voice(self.llm, idn, cov_texts or [idn.description])

        self.stage("queries")
        plan = self._cached_plan()
        if plan is None:
            plan = planner.plan_queries(self.llm, idn, langs, N_QUERIES)
            store.cache_put(db, "query_plan", idn.brand_id, plan.model_dump())
        queries =[(f"{self.run_id}:q{i:02d}", q) for i, q in enumerate(plan.queries)]
        db.executemany("INSERT OR REPLACE INTO queries VALUES (?,?,?,?,?,?,?)",
                       [(qid, self.run_id, q.text, q.lang, q.topic, q.persona_id, q.li_keywords)
                        for qid, q in queries])
        db.commit()

        # Discovery, widening the window when the niche is sparse.
        yt_ids: set[str] = set()
        li_texts: dict[str, str] = {}
        coverage_level, window_days = "normal", idn.window_days
        for attempt, window_days in enumerate(sorted({idn.window_days, 56, 90})):
            if window_days < idn.window_days:
                continue
            since = self.now - timedelta(days=window_days)
            self.stage(f"youtube ({window_days}d)")
            try:
                yt_ids |= collect.youtube_discovery(db, self.yt, queries, markets.regions,
                                                    store.iso(since), DATE_ORDER_QUERIES)
                creators = {r[0] for r in db.execute(
                    f"SELECT DISTINCT creator_id FROM items WHERE item_id IN ({','.join('?' * len(yt_ids))})",
                    list(yt_ids))} if yt_ids else set()
                collect.refresh_channels(db, self.yt, creators)
                collect.youtube_baselines(db, self.yt, creators)
            except QuotaExceeded:
                self.warnings.append("YouTube daily quota exhausted; demand uses the videos collected so far.")
            self.stage(f"linkedin ({window_days}d)")
            li_texts |= collect.linkedin_discovery(db, self.spend, queries, markets.regions, since, self.now)
            self.stage("classify")
            normalize.classify(db, self.llm, idn, sorted(yt_ids | set(li_texts)), li_texts,
                               plan.negative_keywords, main_lang)
            n_rel = self._relevant_count(yt_ids | set(li_texts))
            if n_rel >= config.SPARSE_ITEMS or window_days >= 90 or self.yt.units > 6000:
                break
            coverage_level = {28: "widened_56d", 56: "widened_90d"}.get(window_days, "widened_90d")
            self.warnings.append(f"Only {n_rel} relevant items in {window_days} days; widening the window.")
        if self._relevant_count(yt_ids | set(li_texts)) < config.SPARSE_ITEMS:
            coverage_level = "sparse"
        weeks = max(2, math.ceil(window_days / 7))
        since = self.now - timedelta(days=window_days)

        # Items of this run that the classifier kept.
        rows = self._relevant_rows(yt_ids | set(li_texts))
        collect.track(db, [r["item_id"] for r in rows if r["platform"] == "youtube"], idn.brand_id, window_days)

        self.stage("topics")
        phrase_counts = Counter(r["topic_phrase"] for r in rows if r["topic_phrase"])
        if not phrase_counts:
            raise RuntimeError("No relevant items found for this brand; check the queries and API keys.")
        taxonomy = topic_mod.build_taxonomy(self.llm, idn, phrase_counts, cov_texts, main_lang)
        phrase_map = topic_mod.map_phrases(self.llm, taxonomy, list(phrase_counts))
        tax = {t.topic_id: t for t in taxonomy.topics}

        self.stage("scoring")
        items = self._score_items(rows, phrase_map, since)
        by_id = {it.item_id: it for it in items}
        self.item_topics = {it.item_id: tax[it.topic_id].label for it in items if it.topic_id in tax}
        stats = scoring.topic_stats(items, list(tax), self.now, weeks, main_lang)
        scoring.score_topics(stats)

        self.stage("judge")
        titles = {r["item_id"]: r["title"] or r["excerpt"] or "" for r in rows}
        top_yt = {t: sorted((it for it in items if it.topic_id == t and it.platform == "youtube"),
                            key=lambda it: it.outlier() or 0, reverse=True)[:3] for t in tax}
        top_li = {t: sorted((it for it in items if it.topic_id == t and it.platform == "linkedin"),
                            key=lambda it: it.proxy, reverse=True)[:3] for t in tax}
        judged_ids = sorted(tax, key=lambda t: (stats[t].yt_demand, stats[t].li_items), reverse=True)
        payload = [self._topic_payload(tax[t], stats[t], top_yt[t], top_li[t], titles)
                   for t in judged_ids[:TOP_TOPICS_JUDGED]]
        judgments = opp_mod.judge_topics(self.llm, idn, payload, main_lang)
        persona_ids = [p.id for p in idn.personas]

        topics_out = []
        for t, tt in tax.items():
            s, j = stats[t], judgments.get(t)
            rel = opp_mod.persona_relevance(j, persona_ids)
            brand_fit = round(min(max(j.brand_fit, 0), 1), 3) if j else 0.0
            coverage_gap = round(1 - tt.covered_by_brand, 3) if cov_source else 1.0
            score = scoring.opportunity_score(s, max(rel.values() or [0]), brand_fit, coverage_gap)
            why = [b for b in (j.why_it_works if j else [])
                   if opp_mod.numbers_ok(b, opp_mod.allowed_numbers(payload))]
            labels = scoring.bucket_labels(self.now, weeks)
            topics_out.append(Topic(
                topic_id=t, label=tt.label, entities=tt.entities[:8], maps_to=tt.maps_to,
                stage=s.stage, confidence=s.confidence,
                linkedin=LinkedInTopic(posts_7d=s.li_weekly[-1], authors_7d=s.li_authors_7d,
                                       growth_wow=round(s.li_growth, 3), li_gap=s.li_gap,
                                       trend_status=s.trend_status,
                                       timeseries=[WeekPosts(week=w, posts=n) for w, n in zip(labels, s.li_weekly)]),
                demand=Demand(level=s.demand_level, momentum_wow=round(s.yt_momentum, 3),
                              median_outlier=s.yt_quality, items=s.yt_items,
                              timeseries=[WeekAttention(week=w, attention=round(a, 2))
                                          for w, a in zip(labels, s.yt_weekly)]),
                persona_relevance=rel, brand_fit=brand_fit, coverage_gap=coverage_gap,
                opportunity_score=score, why_it_works=why[:3],
                top_items=[it.item_id for it in top_li[t]] + [it.item_id for it in top_yt[t]]))
        topics_out.sort(key=lambda x: x.opportunity_score, reverse=True)

        self.stage("patterns")
        li_all_top = sorted((it for it in items if it.platform == "linkedin"), key=lambda it: it.proxy,
                            reverse=True)[:50]
        patterns = pat.youtube_lift(items, titles, li_all_top) + pat.linkedin_usage(li_all_top)
        audience = []
        if self.spent() < config.run_budget_usd() * 0.6:
            catalog = "\n".join(f"{t.topic_id}: {t.label}" for t in taxonomy.topics)
            top_videos = sorted((it for it in items if it.platform == "youtube" and it.outlier()),
                                key=lambda it: it.outlier(), reverse=True)
            try:
                audience = pat.audience_voice(self.llm, self.yt, top_videos, catalog, main_lang)
            except Exception as e:
                self.warnings.append(f"Audience voice skipped: {e}")
        else:
            self.warnings.append("Audience voice skipped to stay inside the run budget.")
        asks = {a.topic_id for a in audience if a.topic_id}

        self.stage("opportunities")
        typed = []
        for tp in topics_out:
            s = stats[tp.topic_id]
            kind = opp_mod.opportunity_type(s, max(tp.persona_relevance.values() or [0]), main_lang,
                                            tp.topic_id in asks)
            if kind and tp.opportunity_score > 0:
                typed.append((tp, kind))
        opp_payload = []
        for n, (tp, kind) in enumerate(typed[:TOP_OPPORTUNITIES], 1):
            s = stats[tp.topic_id]
            ev = [self._evidence(by_id[i], titles) for i in tp.top_items if i in by_id]
            opp_payload.append({
                "id": f"op{n}", "type": kind, "topic_id": tp.topic_id, "topic": tp.label,
                "score": tp.opportunity_score, "stage": s.stage, "trend_status": s.trend_status,
                "metrics": {"li_gap": s.li_gap, "linkedin_posts_7d": s.li_weekly[-1],
                            "linkedin_authors_7d": s.li_authors_7d, "linkedin_growth_wow": round(s.li_growth, 2),
                            "youtube_demand_momentum_wow": round(s.yt_momentum, 2),
                            "youtube_median_outlier": s.yt_quality, "youtube_videos": s.yt_items},
                "persona_relevance": tp.persona_relevance,
                "audience_questions": [a.theme for a in audience if a.topic_id == tp.topic_id][:3],
                "evidence_items": ev})
        opps = opp_mod.build_opportunities(self.llm, idn, voice, opp_payload,
                                           [p.model_dump() for p in patterns[:6]], main_lang, self.warnings)

        self.stage("report")
        wanted = {i for tp in topics_out for i in tp.top_items} | {e for o in opps for e in o.evidence} \
            | {e for p in patterns for e in p.examples}
        out_items = [self._out_item(by_id[i], titles, rows) for i in sorted(wanted) if i in by_id]
        yt_creators = {it.creator_id for it in items if it.platform == "youtube"}
        report = Report(
            run=RunInfo(
                run_id=self.run_id, brand_id=idn.brand_id, generated_at=store.iso(store.now_utc()),
                window=Window(**{"from": since.strftime("%Y-%m-%d"), "to": self.now.strftime("%Y-%m-%d")}),
                output_platforms=idn.output_platforms,
                sources=Sources(
                    youtube=YouTubeSource(items=sum(it.platform == "youtube" for it in items),
                                          creators=len(yt_creators), quota_used=self.yt.units,
                                          visibility="public" if "youtube" in idn.output_platforms else "internal"),
                    linkedin=LinkedInSource(items=sum(it.platform == "linkedin" for it in items),
                                            providers=[p for p, n in self.spend.calls.items() if n] or ["cache"])),
                cost_usd=Cost(search=round(self.spend.usd, 3), llm=round(self.llm.usd, 3))),
            brand=BrandInfo(coverage_source=cov_source, coverage_topics=[t.label for t in taxonomy.topics
                                                                        if t.covered_by_brand >= 0.5],
                            voice=voice, languages=markets.languages, regions=markets.regions),
            topics=topics_out, items=out_items, patterns=patterns, audience_voice=audience,
            opportunities=opps,
            data_quality=DataQuality(coverage_level=coverage_level, warnings=self.warnings))
        missing = {e for o in opps for e in o.evidence} - {i.item_id for i in out_items}
        if missing:
            raise RuntimeError(f"Report references unknown evidence ids: {missing}")
        return report

    def youtube_pieces(self) -> list[dict]:
        """Relevant YouTube videos of the finished run with their observed view snapshots (oldest
        first). LinkedIn posts are left out: search indexes expose no views, and none are invented."""
        out = []
        for item_id, topic in self.item_topics.items():
            if not item_id.startswith("yt:"):
                continue
            r = self.db.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
            snaps = self.db.execute("SELECT captured_at, views FROM snapshots WHERE item_id=? "
                                    "ORDER BY captured_at", (item_id,)).fetchall()
            if r and r["published_at"] and snaps:
                out.append({"video_id": item_id.removeprefix("yt:"), "title": r["title"] or "",
                            "topic": topic, "format": r["format"], "published_at": r["published_at"],
                            "snapshots": [(s["captured_at"], s["views"]) for s in snaps]})
        return out

    # --- helpers ---------------------------------------------------------------
    def _cached_plan(self) -> planner.QueryPlan | None:
        """Reuse the brand's query plan for 24 h so reruns hit the search cache instead of spending
        YouTube quota on freshly worded queries."""
        cached = store.cache_get(self.db, "query_plan", self.identity.brand_id)
        if cached:
            return planner.QueryPlan.model_validate(cached)
        since = store.iso(self.now - timedelta(hours=config.SEARCH_CACHE_HOURS))
        prev = self.db.execute("SELECT run_id FROM runs WHERE brand_id=? AND run_id<>? AND started_at>? "
                               "ORDER BY started_at DESC LIMIT 1",
                               (self.identity.brand_id, self.run_id, since)).fetchone()
        rows = self.db.execute("SELECT * FROM queries WHERE run_id=? ORDER BY query_id",
                               (prev[0],)).fetchall() if prev else []
        if not rows:
            return None
        return planner.QueryPlan(negative_keywords=[], queries=[
            planner.PlannedQuery(text=r["text"], li_keywords=r["li_keywords"], lang=r["lang"],
                                 topic=r["topic"], persona_id=r["persona_id"]) for r in rows])

    def _relevant_count(self, ids: set[str]) -> int:
        return len(self._relevant_rows(ids))

    def _relevant_rows(self, ids: set[str]) -> list:
        if not ids:
            return []
        ids = list(ids)
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            out += self.db.execute(
                f"""SELECT i.*, c.topic_phrase, c.hook, c.lang AS clang, c.entities
                    FROM items i JOIN item_class c ON c.item_id = i.item_id AND c.brand_id = ?
                    WHERE c.relevant = 1 AND i.item_id IN ({','.join('?' * len(chunk))})""",
                [self.identity.brand_id, *chunk]).fetchall()
        return out

    def _score_items(self, rows, phrase_map: dict[str, str], since) -> list[scoring.Item]:
        db, items = self.db, []
        baselines = {r["creator_id"]: json.loads(r["baseline"] or "{}")
                     for r in db.execute("SELECT creator_id, baseline FROM creators WHERE platform='youtube'")}
        for r in rows:
            published = store.parse_ts(r["published_at"]) if r["published_at"] else None
            it = scoring.Item(item_id=r["item_id"], platform=r["platform"], creator_id=r["creator_id"],
                              published=published, format=r["format"] or "post",
                              topic_id=phrase_map.get(r["topic_phrase"]), lang=r["clang"] or r["lang"],
                              hook=r["hook"])
            if r["platform"] == "youtube":
                last = store.latest_snapshot(db, r["item_id"])
                if last:
                    it.views, it.likes, it.comments = last["views"], last["likes"], last["comments"]
                    prev = store.previous_snapshot(db, r["item_id"], last["captured_at"])
                    if prev:
                        dt_h = (store.parse_ts(last["captured_at"]) - store.parse_ts(prev["captured_at"])).total_seconds() / 3600
                        if dt_h >= 1:
                            it.momentum_h = round((last["views"] - prev["views"]) / dt_h, 1)
                it.baseline = baselines.get(r["creator_id"], {})
            items.append(it)
        scoring.normalize_attention([it for it in items if it.platform == "youtube"], self.now)

        # LinkedIn visibility proxies from this run's ranks.
        li = [it for it in items if it.platform == "linkedin"]
        if li:
            hits: dict[str, list] = {}
            for h in db.execute(
                    f"SELECT item_id, query_id, provider, rank FROM item_query WHERE query_id LIKE ? "
                    f"AND item_id IN ({','.join('?' * len(li))})", [f"{self.run_id}:%", *[it.item_id for it in li]]):
                hits.setdefault(h["item_id"], []).append((h["query_id"], h["provider"], h["rank"]))
            per_author = Counter(it.creator_id for it in li if it.creator_id)
            author_counts = {it.item_id: per_author.get(it.creator_id, 0) for it in li}
            ages = {it.item_id: (self.now - it.published).days if it.published else 14 for it in li}
            n_queries = self.db.execute("SELECT COUNT(*) FROM queries WHERE run_id=?", (self.run_id,)).fetchone()[0]
            proxies = linkedin.visibility_proxies(hits, author_counts, ages, n_queries)
            for it in li:
                it.proxy = proxies.get(it.item_id, 0.0)
        return items

    def _topic_payload(self, tt, s: scoring.TopicStats, top_yt, top_li, titles) -> dict:
        return {
            "topic_id": tt.topic_id, "label": tt.label, "description": tt.description,
            "stage": s.stage, "trend_status": s.trend_status,
            "youtube": {"videos": s.yt_items, "demand_momentum_wow": round(s.yt_momentum, 2),
                        "median_outlier": s.yt_quality,
                        "top_videos": [{"title": titles.get(it.item_id, ""), "views": it.views,
                                        "outlier": it.outlier()} for it in top_yt]},
            "linkedin": {"posts_in_window": s.li_items, "posts_7d": s.li_weekly[-1],
                         "authors_7d": s.li_authors_7d, "growth_wow": round(s.li_growth, 2),
                         "li_gap": s.li_gap,
                         "top_posts": [titles.get(it.item_id, "")[:200] for it in top_li]},
        }

    def _evidence(self, it: scoring.Item, titles) -> dict:
        e = {"item_id": it.item_id, "platform": it.platform, "text": titles.get(it.item_id, "")[:200]}
        if it.platform == "youtube":
            e |= {"views": it.views, "outlier": it.outlier()}
        return e

    def _out_item(self, it: scoring.Item, titles, rows) -> OutItem:
        r = next(x for x in rows if x["item_id"] == it.item_id)
        author = None
        if it.creator_id:
            c = self.db.execute("SELECT display_name FROM creators WHERE creator_id=?", (it.creator_id,)).fetchone()
            author = c["display_name"] if c else None
        common = dict(item_id=it.item_id, platform=it.platform, url=r["url"], author=author,
                      published_at=r["published_at"], format=it.format, lang=it.lang, hook=it.hook)
        if it.platform == "youtube":
            age = scoring.age_hours(it, self.now)
            return OutItem(**common, title=r["title"],
                           visibility="public" if "youtube" in self.identity.output_platforms else "internal",
                           metrics=ItemMetrics(views=it.views, outlier=it.outlier(), engagement=it.engagement(),
                                               velocity_h=round(it.views / age, 1)),
                           evidence_level="api")
        return OutItem(**common, title=r["title"], excerpt=r["excerpt"], visibility_proxy=it.proxy,
                       evidence_level="search_index")


def run(identity: BrandIdentity, run_id: str | None = None, on_stage=None) -> Report:
    return Run(identity, run_id, on_stage).execute()
