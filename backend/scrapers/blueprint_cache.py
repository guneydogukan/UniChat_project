"""
UniChat — Faz 4.1.3: Blueprint (Menü Ağacı) Önbellek Mekanizması

Parse edilmiş MenuTree nesnelerini JSON ile cache'ler.
Aynı blueprint tekrar istendiğinde dosya parse etmeden cache'den okur.
Dosya değiştiğinde (mtime kontrolü) cache otomatik invalidate olur.

Kullanım:
    from scrapers.blueprint_cache import BlueprintCache

    cache = BlueprintCache()

    # İlk çağrı: parse + cache yaz
    tree = cache.get_or_parse("doc/gibtu/.../MDBF.html")

    # Sonraki çağrı: cache'den oku (çok hızlı)
    tree = cache.get_or_parse("doc/gibtu/.../MDBF.html")

    # Cache temizle
    cache.clear()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache dizini
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_CACHE_DIR = _BACKEND_DIR / "scrapers" / ".blueprint_cache"


class BlueprintCache:
    """
    Parse edilmiş menü ağaçlarını JSON olarak önbelleğe alır.

    Cache stratejisi:
      - Anahtar: blueprint dosya yolunun SHA-256 hash'i
      - Değer: MenuTree.to_dict() + metadata (mtime, parse_time)
      - Invalidation: dosya mtime değişiklik kontrolü
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or _CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, Any] = {}  # İn-memory cache (session boyunca)

    def _cache_key(self, blueprint_path: str | Path) -> str:
        """Blueprint yolu için cache anahtarı üretir."""
        abs_path = str(Path(blueprint_path).resolve())
        return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]

    def _cache_file(self, key: str) -> Path:
        """Cache dosya yolunu döndürür."""
        return self.cache_dir / f"{key}.json"

    def _get_mtime(self, blueprint_path: str | Path) -> float:
        """Dosyanın son değişiklik zamanını döndürür."""
        try:
            return os.path.getmtime(str(blueprint_path))
        except OSError:
            return 0.0

    def get_or_parse(self, blueprint_path: str | Path):
        """
        Blueprint'i cache'den okur veya parse edip cache'e yazar.

        Args:
            blueprint_path: Blueprint HTML dosya yolu.

        Returns:
            MenuTree nesnesi.
        """
        from scrapers.blueprint_parser import parse_blueprint

        bp_path = Path(blueprint_path).resolve()
        if not bp_path.exists():
            raise FileNotFoundError(f"Blueprint bulunamadı: {bp_path}")

        key = self._cache_key(bp_path)
        current_mtime = self._get_mtime(bp_path)

        # 1. In-memory cache kontrolü
        if key in self._memory_cache:
            cached = self._memory_cache[key]
            if cached.get("mtime") == current_mtime:
                logger.debug("Cache HIT (memory): %s", bp_path.name)
                return cached["tree"]

        # 2. Disk cache kontrolü
        cache_file = self._cache_file(key)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)

                cached_mtime = cache_data.get("mtime", 0)
                if cached_mtime == current_mtime:
                    # Cache geçerli — MenuTree'yi JSON'dan yeniden oluştur
                    tree = self._dict_to_menu_tree(cache_data["tree"])
                    self._memory_cache[key] = {
                        "tree": tree,
                        "mtime": current_mtime,
                    }
                    logger.debug("Cache HIT (disk): %s", bp_path.name)
                    return tree
                else:
                    logger.debug("Cache STALE (mtime changed): %s", bp_path.name)
            except (json.JSONDecodeError, KeyError, Exception) as e:
                logger.debug("Cache READ ERROR: %s — %s", bp_path.name, e)

        # 3. Cache MISS — parse et
        logger.info("Cache MISS — parsing: %s", bp_path.name)
        start = time.time()
        tree = parse_blueprint(bp_path)
        parse_time = time.time() - start

        # Cache'e yaz
        self._write_cache(key, tree, current_mtime, parse_time, str(bp_path))

        # In-memory cache güncelle
        self._memory_cache[key] = {
            "tree": tree,
            "mtime": current_mtime,
        }

        logger.info(
            "  Parsed + cached: %d items, %.2fs",
            len(tree.items), parse_time,
        )
        return tree

    def _write_cache(
        self, key: str, tree, mtime: float, parse_time: float, source: str
    ):
        """MenuTree'yi JSON olarak cache'e yazar."""
        cache_data = {
            "mtime": mtime,
            "parse_time_seconds": round(parse_time, 3),
            "source": source,
            "cached_at": time.time(),
            "tree": self._menu_tree_to_dict(tree),
        }

        cache_file = self._cache_file(key)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=1)
            logger.debug("Cache WRITE: %s → %s", source, cache_file.name)
        except Exception as e:
            logger.warning("Cache WRITE ERROR: %s — %s", cache_file, e)

    def _menu_tree_to_dict(self, tree) -> dict:
        """MenuTree'yi JSON-serializable dict'e dönüştürür."""
        return {
            "birim_id": tree.birim_id,
            "birim_title": tree.birim_title,
            "source_file": tree.source_file if hasattr(tree, "source_file") else "",
            "items": [
                {
                    "title": item.title,
                    "is_parent": item.is_parent,
                    "link": {
                        "href": item.link.href,
                        "text": item.link.text,
                        "url": item.link.url,
                        "link_type": item.link.link_type.value,
                    } if item.link else None,
                    "children": [
                        {
                            "href": link.href,
                            "text": link.text,
                            "url": link.url,
                            "link_type": link.link_type.value,
                        }
                        for link in item.children
                    ],
                    "all_links": [
                        {
                            "href": link.href,
                            "text": link.text,
                            "url": link.url,
                            "link_type": link.link_type.value,
                        }
                        for link in item.all_links
                    ],
                }
                for item in tree.items
            ],
        }

    def _dict_to_menu_tree(self, data: dict):
        """JSON dict'ten MenuTree nesnesini yeniden oluşturur."""
        from scrapers.blueprint_parser import MenuTree, MenuItem, MenuLink, LinkType

        def _make_link(d: dict) -> MenuLink:
            return MenuLink(
                href=d.get("href", d.get("url", "")),
                url=d.get("url", ""),
                text=d.get("text", ""),
                link_type=LinkType(d.get("link_type", "page")),
            )

        items = []
        for item_data in data.get("items", []):
            # Header link
            header_link = None
            link_data = item_data.get("link")
            if link_data and isinstance(link_data, dict):
                header_link = _make_link(link_data)
            elif not link_data:
                # Eski format uyumluluğu: all_links'ten ilk elemanı kullan
                raw_links = item_data.get("all_links", [])
                if raw_links:
                    header_link = _make_link(raw_links[0])

            # Children
            children_raw = item_data.get("children", [])
            children = [_make_link(c) for c in children_raw]

            # Eski format: children boşsa all_links'ten türet
            if not children:
                raw_links = item_data.get("all_links", [])
                if len(raw_links) > 1:
                    children = [_make_link(l) for l in raw_links[1:]]

            item = MenuItem(
                title=item_data.get("title", ""),
                link=header_link,
                children=children,
                is_parent=item_data.get("is_parent", False),
            )
            items.append(item)

        tree = MenuTree(
            birim_id=data.get("birim_id"),
            birim_title=data.get("birim_title", ""),
            items=items,
        )
        return tree

    def invalidate(self, blueprint_path: str | Path):
        """Belirli bir blueprint'in cache'ini siler."""
        key = self._cache_key(Path(blueprint_path).resolve())
        cache_file = self._cache_file(key)
        if cache_file.exists():
            cache_file.unlink()
        self._memory_cache.pop(key, None)
        logger.info("Cache invalidated: %s", blueprint_path)

    def clear(self):
        """Tüm cache'i temizler."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        self._memory_cache.clear()
        logger.info("Cache cleared: %d dosya silindi", count)

    def stats(self) -> dict:
        """Cache istatistikleri."""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "cache_dir": str(self.cache_dir),
            "file_count": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "memory_cache_count": len(self._memory_cache),
        }


# ── Modül Seviyesi Singleton ──
_default_cache: BlueprintCache | None = None


def get_cache() -> BlueprintCache:
    """Singleton BlueprintCache döndürür."""
    global _default_cache
    if _default_cache is None:
        _default_cache = BlueprintCache()
    return _default_cache
