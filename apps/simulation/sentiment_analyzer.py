"""
Sentiment Analysis for EcoSim Campaign Reports.

Uses open-source HuggingFace models for local inference (no API key needed):
- Primary:  cardiffnlp/twitter-roberta-base-sentiment (3-class, social media)
- Fallback: distilbert-base-uncased-finetuned-sst-2-english (2-class, fast)

Usage:
    from sentiment_analyzer import SentimentAnalyzer
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze("I love this product!")
    # {'label': 'positive', 'score': 0.95}

    batch = analyzer.analyze_batch(["Great!", "Terrible.", "It's okay."])
    # [{'label': 'positive', ...}, {'label': 'negative', ...}, {'label': 'neutral', ...}]
"""
import json
import logging
import os
import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("ecosim.sentiment")

# Model configs (downloaded on first use, cached in ~/.cache/huggingface)
MODELS = {
    "twitter-roberta": {
        "name": "cardiffnlp/twitter-roberta-base-sentiment-latest",
        "labels": {
            "negative": "negative",
            "neutral": "neutral",
            "positive": "positive",
        },
        "description": "RoBERTa trained on ~124M tweets, 3-class sentiment",
    },
    "distilbert": {
        "name": "distilbert-base-uncased-finetuned-sst-2-english",
        "labels": {
            "NEGATIVE": "negative",
            "POSITIVE": "positive",
        },
        "description": "DistilBERT, 2-class (no neutral), very fast",
    },
}

DEFAULT_MODEL = "twitter-roberta"


class SentimentAnalyzer:
    """Local sentiment analysis using HuggingFace transformers."""

    def __init__(self, model_key: str = DEFAULT_MODEL):
        self.model_key = model_key
        self.config = MODELS[model_key]
        self._pipeline = None

    def _load(self):
        """Lazy-load the model pipeline on first use."""
        if self._pipeline is not None:
            return

        try:
            from transformers import pipeline as hf_pipeline
            logger.info(f"Loading sentiment model: {self.config['name']}")
            self._pipeline = hf_pipeline(
                "sentiment-analysis",
                model=self.config["name"],
                truncation=True,
                max_length=512,
            )
            logger.info("Sentiment model loaded successfully")
        except ImportError:
            raise RuntimeError(
                "transformers not installed. Run: pip install transformers torch"
            )
        except Exception as e:
            # Try fallback model
            if self.model_key != "distilbert":
                logger.warning(f"Primary model failed ({e}), trying distilbert fallback")
                self.model_key = "distilbert"
                self.config = MODELS["distilbert"]
                self._pipeline = None
                self._load()
            else:
                raise

    def analyze(self, text: str) -> Dict:
        """Analyze sentiment of a single text.

        Returns:
            {'label': 'positive'|'neutral'|'negative', 'score': float}
        """
        self._load()
        if not text or not text.strip():
            return {"label": "neutral", "score": 0.5}

        result = self._pipeline(text[:512])[0]
        raw_label = result["label"]
        normalized = self.config["labels"].get(raw_label, raw_label.lower())

        return {
            "label": normalized,
            "score": round(result["score"], 4),
            "raw_label": raw_label,
        }

    def analyze_batch(self, texts: List[str], batch_size: int = 32) -> List[Dict]:
        """Analyze sentiment of multiple texts efficiently.

        Returns list of {'label': str, 'score': float} dicts.
        """
        self._load()
        if not texts:
            return []

        # Clean and truncate
        cleaned = [t[:512] if t and t.strip() else "" for t in texts]

        results = []
        for i in range(0, len(cleaned), batch_size):
            batch = cleaned[i:i + batch_size]
            # Filter empty
            non_empty_indices = [j for j, t in enumerate(batch) if t.strip()]
            non_empty_texts = [batch[j] for j in non_empty_indices]

            if non_empty_texts:
                raw_results = self._pipeline(non_empty_texts)
            else:
                raw_results = []

            # Map back
            batch_results = [{"label": "neutral", "score": 0.5}] * len(batch)
            for idx, raw in zip(non_empty_indices, raw_results):
                raw_label = raw["label"]
                normalized = self.config["labels"].get(raw_label, raw_label.lower())
                batch_results[idx] = {
                    "label": normalized,
                    "score": round(raw["score"], 4),
                }

            results.extend(batch_results)

        return results

    @property
    def model_name(self) -> str:
        return self.config["name"]


# ═══════════════════════════════════════════════════════
# Campaign Report Generator
# ═══════════════════════════════════════════════════════

class CampaignReportGenerator:
    """Generate campaign effectiveness report from simulation data."""

    def __init__(self, db_path: str, actions_path: str = None):
        self.db_path = db_path
        self.actions_path = actions_path
        self._analyzer = None

    @property
    def analyzer(self):
        if self._analyzer is None:
            self._analyzer = SentimentAnalyzer()
        return self._analyzer

    def _query_db(self, sql: str, params=()) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def get_quantitative_metrics(self) -> Dict:
        """Get raw counts: posts, likes, comments, unique agents."""
        posts = self._query_db("SELECT COUNT(*) as n FROM post")[0]["n"]
        comments = self._query_db("SELECT COUNT(*) as n FROM comment")[0]["n"]
        likes = self._query_db("SELECT COUNT(*) as n FROM [like]")[0]["n"]
        agents = self._query_db("SELECT COUNT(DISTINCT user_id) as n FROM post")[0]["n"]
        unique_commenters = self._query_db(
            "SELECT COUNT(DISTINCT user_id) as n FROM comment"
        )[0]["n"]
        total_agents = self._query_db("SELECT COUNT(*) as n FROM user")[0]["n"]
        traces = self._query_db("SELECT COUNT(*) as n FROM trace")[0]["n"]

        comments_per_post = round(comments / max(posts, 1), 2)
        likes_per_post = round(likes / max(posts, 1), 2)

        return {
            "total_posts": posts,
            "total_comments": comments,
            "total_likes": likes,
            "total_agents": total_agents,
            "unique_posters": agents,
            "unique_commenters": unique_commenters,
            "total_traces": traces,
            "comments_per_post": comments_per_post,
            "likes_per_post": likes_per_post,
        }

    def get_engagement_rate(self, num_rounds: int = 1) -> Dict:
        """Calculate engagement rate.
        ER = (likes + comments) / (agents × rounds) × 100
        """
        m = self.get_quantitative_metrics()
        total_interactions = m["total_likes"] + m["total_comments"]
        denominator = max(m["total_agents"] * num_rounds, 1)
        er = round(total_interactions / denominator * 100, 2)

        if er < 1:
            rating = "LOW"
        elif er < 3:
            rating = "AVERAGE"
        elif er < 6:
            rating = "GOOD"
        else:
            rating = "EXCELLENT"

        return {
            "engagement_rate": er,
            "rating": rating,
            "total_interactions": total_interactions,
            "agents": m["total_agents"],
            "rounds": num_rounds,
        }

    def analyze_comment_sentiment(self) -> Dict:
        """Analyze sentiment of all comments.

        Returns:
            {
                'distribution': {'positive': 30, 'neutral': 15, 'negative': 5},
                'nss': 50.0,  # Net Sentiment Score
                'details': [{'comment_id': 1, 'content': '...', 'sentiment': 'positive', 'score': 0.95}, ...]
            }
        """
        comments = self._query_db(
            "SELECT comment_id, user_id, content, post_id FROM comment"
        )

        if not comments:
            return {
                "distribution": {"positive": 0, "neutral": 0, "negative": 0},
                "nss": 0.0,
                "details": [],
                "model": "n/a",
            }

        texts = [c["content"] for c in comments]
        sentiments = self.analyzer.analyze_batch(texts)

        distribution = {"positive": 0, "neutral": 0, "negative": 0}
        details = []

        for comment, sent in zip(comments, sentiments):
            label = sent["label"]
            distribution[label] = distribution.get(label, 0) + 1
            details.append({
                "comment_id": comment["comment_id"],
                "user_id": comment["user_id"],
                "post_id": comment["post_id"],
                "content": comment["content"][:200],
                "sentiment": label,
                "score": sent["score"],
            })

        total = len(comments)
        pos_pct = distribution["positive"] / max(total, 1) * 100
        neg_pct = distribution["negative"] / max(total, 1) * 100
        nss = round(pos_pct - neg_pct, 2)

        return {
            "distribution": distribution,
            "nss": nss,
            "total_comments": total,
            "positive_pct": round(pos_pct, 1),
            "neutral_pct": round(100 - pos_pct - neg_pct, 1),
            "negative_pct": round(neg_pct, 1),
            "details": details,
            "model": self.analyzer.model_name,
        }

    def get_per_round_metrics(self) -> List[Dict]:
        """Get metrics broken down by round (from actions.jsonl)."""
        if not self.actions_path or not os.path.exists(self.actions_path):
            return []

        round_data = defaultdict(lambda: {
            "posts": 0, "likes": 0, "comments": 0, "comment_texts": []
        })

        with open(self.actions_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    action = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rnd = action.get("round", 0)
                atype = action.get("action_type", "")

                if atype == "create_post":
                    round_data[rnd]["posts"] += 1
                elif atype == "like":
                    round_data[rnd]["likes"] += 1
                elif atype == "create_comment":
                    round_data[rnd]["comments"] += 1
                    info = action.get("info", {})
                    if isinstance(info, str):
                        try:
                            info = json.loads(info)
                        except (json.JSONDecodeError, TypeError):
                            info = {}
                    content = info.get("content", "")
                    if content:
                        round_data[rnd]["comment_texts"].append(content)

        if not round_data:
            return []

        # Analyze sentiment per round
        results = []
        for rnd in sorted(round_data.keys()):
            data = round_data[rnd]
            sentiment_dist = {"positive": 0, "neutral": 0, "negative": 0}

            if data["comment_texts"]:
                sentiments = self.analyzer.analyze_batch(data["comment_texts"])
                for s in sentiments:
                    sentiment_dist[s["label"]] = sentiment_dist.get(s["label"], 0) + 1

            total_comments = max(len(data["comment_texts"]), 1)
            nss = round(
                (sentiment_dist["positive"] - sentiment_dist["negative"])
                / total_comments * 100, 1
            )

            results.append({
                "round": rnd,
                "posts": data["posts"],
                "likes": data["likes"],
                "comments": data["comments"],
                "sentiment": sentiment_dist,
                "nss": nss,
            })

        return results

    def generate_campaign_score(self, num_rounds: int = 1) -> Dict:
        """Calculate overall campaign effectiveness score [0-1].

        Score = w1×ER_norm + w2×NSS_norm + w3×Growth_norm + w4×Diversity_norm
        """
        metrics = self.get_quantitative_metrics()
        er_data = self.get_engagement_rate(num_rounds)
        sentiment = self.analyze_comment_sentiment()

        er_norm = min(er_data["engagement_rate"] / 10.0, 1.0)
        nss_norm = (sentiment["nss"] + 100) / 200.0
        diversity_norm = metrics["unique_commenters"] / max(metrics["total_agents"], 1)

        # Growth: compare last round vs first round (if per-round data available)
        growth_norm = 0.5  # default neutral
        per_round = self.get_per_round_metrics()
        if len(per_round) >= 2:
            first_er = (per_round[0]["likes"] + per_round[0]["comments"])
            last_er = (per_round[-1]["likes"] + per_round[-1]["comments"])
            if first_er > 0:
                growth = (last_er - first_er) / first_er
                growth_norm = min(max((growth + 1) / 2, 0), 1)

        # Weighted score
        w1, w2, w3, w4 = 0.3, 0.3, 0.2, 0.2
        score = w1 * er_norm + w2 * nss_norm + w3 * growth_norm + w4 * diversity_norm
        score = round(min(max(score, 0), 1), 3)

        if score >= 0.9:
            rating = "EXCELLENT"
        elif score >= 0.7:
            rating = "GOOD"
        elif score >= 0.5:
            rating = "ACCEPTABLE"
        elif score >= 0.3:
            rating = "BELOW_EXPECTATIONS"
        else:
            rating = "FAILED"

        return {
            "campaign_score": score,
            "rating": rating,
            "components": {
                "engagement_norm": round(er_norm, 3),
                "sentiment_norm": round(nss_norm, 3),
                "growth_norm": round(growth_norm, 3),
                "diversity_norm": round(diversity_norm, 3),
            },
            "weights": {"engagement": w1, "sentiment": w2, "growth": w3, "diversity": w4},
        }

    def generate_full_report(self, num_rounds: int = 1) -> Dict:
        """Generate complete campaign effectiveness report."""
        return {
            "quantitative": self.get_quantitative_metrics(),
            "engagement": self.get_engagement_rate(num_rounds),
            "sentiment": self.analyze_comment_sentiment(),
            "per_round": self.get_per_round_metrics(),
            "campaign_score": self.generate_campaign_score(num_rounds),
        }
