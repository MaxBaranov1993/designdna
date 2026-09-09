"""Слой хранения DesignDNA.

Все SQLite-базы приложения (`projects.db`, `design_systems.db`, `cache.db`)
открываются одним способом — `storage.db.connect` с общими прагмами и
таймаутами — и ведут версию схемы в таблице `schema_versions`. Состояние
всех баз доступно через `storage.db.status()` и `GET /api/storage/status`.
"""
