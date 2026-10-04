from .base import BaseCategorySpider
from .pazar3_spider import Pazar3Spider
from .reklama5_spider import Reklama5Spider
from .imoti247_spider import Imoti247Spider

SITE_SPIDERS = {
    "PAZAR3": Pazar3Spider,
    "REKLAMA5": Reklama5Spider,
    "IMOTI247": Imoti247Spider,
}

__all__ = [
    "BaseCategorySpider",
    "Pazar3Spider",
    "Reklama5Spider",
    "Imoti247Spider",
    "SITE_SPIDERS",
]
