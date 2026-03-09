"""Serialization and deserialization of the index to/from JSON files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from rts.models import IndexData

logger = logging.getLogger(__name__)

# Default index directory name (created inside the repo)
INDEX_DIR_NAME = ".rts"
INDEX_FILE_NAME = "index.json"


class IndexStore:
    """Handles persistence of the index to the filesystem."""

    def __init__(self, repo_root: Path, index_dir: Path | None = None) -> None:
        """Initialize the store.

        Args:
            repo_root: Root of the repository.
            index_dir: Optional override for the index directory.
                       Defaults to <repo_root>/.rts/
        """
        self.repo_root = repo_root
        if index_dir:
            self.index_dir = index_dir
        else:
            self.index_dir = repo_root / INDEX_DIR_NAME

    @property
    def index_path(self) -> Path:
        return self.index_dir / INDEX_FILE_NAME

    def save(self, index_data: IndexData) -> Path:
        """Save the index to a JSON file.

        Args:
            index_data: The index data to persist.

        Returns:
            Path to the saved index file.
        """
        self.index_dir.mkdir(parents=True, exist_ok=True)

        data = index_data.to_dict()
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Index saved to %s", self.index_path)
        return self.index_path

    def load(self) -> IndexData:
        """Load the index from a JSON file.

        Returns:
            The loaded IndexData.

        Raises:
            FileNotFoundError: If the index file does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
        """
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"No index found at {self.index_path}. "
                f"Run 'rts index' first to build the index."
            )

        with open(self.index_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        index = IndexData.from_dict(data)
        logger.info(
            "Index loaded from %s (%d files)",
            self.index_path,
            len(index.files),
        )
        return index

    def exists(self) -> bool:
        """Check if an index file exists."""
        return self.index_path.exists()
