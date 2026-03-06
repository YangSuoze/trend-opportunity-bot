from trendbot.collectors.devto import DEFAULT_DEVTO_TAGS, DevToCollector
from trendbot.collectors.github import DEFAULT_GITHUB_QUERIES, GitHubCollector
from trendbot.collectors.hackernews import HackerNewsCollector
from trendbot.collectors.producthunt import ProductHuntCollector
from trendbot.collectors.reddit import DEFAULT_REDDIT_SUBREDDITS, RedditCollector
from trendbot.collectors.substack import SubstackCollector

__all__ = [
    "DEFAULT_DEVTO_TAGS",
    "DEFAULT_GITHUB_QUERIES",
    "DEFAULT_REDDIT_SUBREDDITS",
    "DevToCollector",
    "GitHubCollector",
    "HackerNewsCollector",
    "ProductHuntCollector",
    "RedditCollector",
    "SubstackCollector",
]
